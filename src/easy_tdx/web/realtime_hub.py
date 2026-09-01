"""WebSocket 实时推送枢纽：RealtimeDataFeed（轮询）→ EventBus → 每连接队列 fan-out。

架构对齐 :class:`easy_tdx.web.quote_streamer.QuoteStreamer`（SSE 推送器）的
生命周期与节能语义，差异在数据通路：

- SSE ``/stream/quotes``：固定集合（指数 + 全部自选）全量快照，所有页面共享；
- WS  ``/ws/realtime/{symbol}``：**按需订阅**的逐标的 tick 事件，走
  :class:`~easy_tdx.realtime.feed.RealtimeDataFeed`（轮询 ``get_stock_quotes``
  五档快照 → :class:`~easy_tdx.realtime.engine.EventBus` 发布 MarketEvent）。

节能语义：

- 订阅集合为空时不轮询（feed 任务不启动 / 已启动则停止）——与 QuoteStreamer
  「无人订阅时循环休眠」一致；
- 轮询集合 = 各连接订阅的去重并集（引用计数）；集合变化时重启 feed
  （feed 的 symbols 在构造时固定，重启代价 ≤ 一个 sleep 步长 0.5s）；
- 盘外时段由 RealtimeDataFeed 自带的交易时段过滤兜底（只睡不拉）。

背压：队列满（连接消费慢）时丢最旧保最新——行情快照旧帧无价值。
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Any

from easy_tdx.realtime.engine import EventBus, MarketEvent
from easy_tdx.realtime.feed import RealtimeDataFeed

logger = logging.getLogger(__name__)

__all__ = ["RealtimeStreamHub", "parse_realtime_symbol", "MAX_WS_SYMBOLS"]

#: 单 hub 订阅标的上限（get_stock_quotes 单次 80 只，协议约束）。
MAX_WS_SYMBOLS = 80

_MARKET_STR_TO_INT: dict[str, int] = {"SZ": 0, "SH": 1, "BJ": 2}


def parse_realtime_symbol(symbol: str) -> tuple[int, str]:
    """``"SZ000001"`` → ``(0, "000001")``（MAC 客户端的 int 市场约定）。

    Raises:
        ValueError: 格式非法（非 市场前缀 + 6 位数字）。
    """
    s = symbol.strip().upper()
    if len(s) != 8 or s[:2] not in _MARKET_STR_TO_INT or not s[2:].isdigit():
        raise ValueError(
            f"标的格式应为 市场前缀+6位代码（如 SZ000001 / SH600519），得到 '{symbol}'"
        )
    return _MARKET_STR_TO_INT[s[:2]], s[2:]


def _event_to_frame(event: MarketEvent) -> dict[str, Any]:
    """MarketEvent → 前端推送帧 ``{type, symbol, price, ts, ...}``。"""
    symbol = f"{event.market}{event.code}"
    return {
        "type": "tick",
        "symbol": symbol,
        "market": event.market,
        "code": event.code,
        "price": event.price,
        "volume": event.volume,
        "ts": event.timestamp if event.timestamp > 0 else time.time(),
        **event.data,  # open/high/low/pre_close/amount/name 等（feed 附加字段）
    }


class RealtimeStreamHub:
    """按需轮询 + 每连接独立队列 fan-out。由 FastAPI lifespan 挂载到
    ``app.state.realtime_hub``，``/ws/realtime/*`` 端点调用。

    Args:
        quote_client: 拥有 ``async def get_stock_quotes(stocks, fields=None)``
            的客户端（如 :class:`~easy_tdx.mac.client.AsyncMacClient`）。
            stocks 为 ``[(market_int, code), ...]``，返回列含
            market/code/close/vol/open/high/low/pre_close/amount/name。
        interval: 轮询间隔（秒），透传给 RealtimeDataFeed。
        sessions: 交易时段过滤，None = feed 默认（A 股时段）；``()`` = 全天轮询
            （演示/E2E 用，配合 mock 数据不受交易时段限制）。
        queue_size: 每连接队列容量（满则丢最旧保最新）。
    """

    def __init__(
        self,
        quote_client: Any,
        *,
        interval: float = 3.0,
        sessions: tuple[tuple[int, int], ...] | None = None,
        queue_size: int = 8,
    ) -> None:
        self._client = quote_client
        self._interval = interval
        self._sessions = sessions
        self._queue_size = queue_size
        self._bus = EventBus()
        self._bus.subscribe_all(self._on_event)
        self._queues: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._subs: dict[int, set[str]] = {}
        self._refcount: dict[str, int] = {}
        self._ids = itertools.count(1)
        self._feed: RealtimeDataFeed | None = None
        self._feed_task: asyncio.Task[None] | None = None
        self._polling: list[tuple[int, str]] = []  # 当前 feed 正在轮询的集合
        self._lock = asyncio.Lock()

    # ── 订阅管理（WS 端点调用） ──────────────────────────────────────────

    def connect(self) -> tuple[int, asyncio.Queue[dict[str, Any]]]:
        """注册一个连接；返回 (cid, queue)。queue 是该连接唯一的推送出口。"""
        cid = next(self._ids)
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._queues[cid] = q
        self._subs[cid] = set()
        return cid, q

    async def subscribe(self, cid: int, symbol: str) -> None:
        """连接 cid 订阅 symbol（引用计数 +1；新标的进入轮询集合）。

        Raises:
            ValueError: symbol 格式非法，或去重后标的数超过 :data:`MAX_WS_SYMBOLS`。
        """
        parse_realtime_symbol(symbol)  # 先做格式校验（不持锁）
        key = symbol.strip().upper()
        async with self._lock:
            if key in self._subs[cid]:
                return  # 幂等：同连接重复订阅同一标的
            if self._refcount.get(key, 0) == 0 and len(self._active_symbols()) >= MAX_WS_SYMBOLS:
                raise ValueError(
                    f"订阅标的总数已达上限 {MAX_WS_SYMBOLS}（get_stock_quotes 单次上限）"
                )
            self._subs[cid].add(key)
            self._refcount[key] = self._refcount.get(key, 0) + 1
            await self._sync_feed()

    async def unsubscribe(self, cid: int, symbol: str) -> None:
        """连接 cid 退订 symbol（引用计数 -1；归零则移出轮询集合）。"""
        key = symbol.strip().upper()
        async with self._lock:
            if key not in self._subs[cid]:
                return
            self._subs[cid].discard(key)
            self._dec_ref(key)
            await self._sync_feed()

    async def disconnect(self, cid: int) -> None:
        """连接断开：退订其全部标的并同步轮询集合。"""
        async with self._lock:
            for key in self._subs.pop(cid, set()):
                self._dec_ref(key)
            self._queues.pop(cid, None)
            await self._sync_feed()

    # ── 生命周期 ──────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """lifespan 关闭时调用：停止轮询任务（feed 正常退出，非 cancel）。"""
        async with self._lock:
            self._refcount.clear()
            await self._stop_feed()

    @property
    def poll_symbols(self) -> list[str]:
        """当前去重后的订阅集合（诊断/测试用）。"""
        return self._active_symbols()

    @property
    def subscriber_count(self) -> int:
        """当前连接数。"""
        return len(self._queues)

    @property
    def polling(self) -> bool:
        """是否正在轮询（有订阅时 True）。"""
        return self._feed_task is not None and not self._feed_task.done()

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _active_symbols(self) -> list[str]:
        """引用计数 > 0 的标的（排序保证 feed 重启的参数确定性）。"""
        return sorted(s for s, c in self._refcount.items() if c > 0)

    def _dec_ref(self, key: str) -> None:
        count = self._refcount.get(key, 0) - 1
        if count > 0:
            self._refcount[key] = count
        else:
            self._refcount.pop(key, None)

    async def _sync_feed(self) -> None:
        """把轮询集合同步成订阅并集（持锁调用）。

        集合未变直接返回；变化则停旧 feed、按新集合启动（空集合 = 完全停止）。
        """
        desired = [parse_realtime_symbol(s) for s in self._active_symbols()]
        if desired == self._polling:
            return
        await self._stop_feed()
        if desired:
            self._feed = RealtimeDataFeed(
                self._bus, desired, interval=self._interval, sessions=self._sessions
            )
            self._feed_task = asyncio.get_running_loop().create_task(
                self._feed.run_async(self._client)
            )
            self._polling = desired
            logger.info("RealtimeStreamHub 开始轮询 %d 只标的", len(desired))
        else:
            logger.info("RealtimeStreamHub 无订阅，停止轮询")

    async def _stop_feed(self) -> None:
        """优雅停止当前 feed 任务（持锁调用）。"""
        if self._feed_task is None:
            return
        if self._feed is not None:
            self._feed.stop()  # 下一 sleep 步长（≤0.5s）内退出
        try:
            await self._feed_task
        except Exception:
            logger.warning("RealtimeDataFeed 任务异常退出", exc_info=True)
        self._feed_task = None
        self._feed = None
        self._polling = []

    def _on_event(self, event: MarketEvent) -> None:
        """EventBus 回调：按各连接的订阅集合 fan-out（丢最旧保最新）。"""
        if not self._queues:
            return
        key = f"{event.market}{event.code}"
        frame = _event_to_frame(event)
        for cid, q in list(self._queues.items()):
            if key not in self._subs.get(cid, set()):
                continue
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(frame)
                except asyncio.QueueFull:
                    pass
