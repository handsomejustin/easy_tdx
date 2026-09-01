"""轮询数据源：把 ``get_stock_quotes`` 的快照喂给 :class:`EventBus`。

通达信协议是请求/响应，没有服务端推送，所以「实时」只能靠**轮询五档快照**
近似实现。本模块提供 :class:`RealtimeDataFeed`，自动完成::

    get_stock_quotes → MarketEvent → bus.publish

让 :class:`~easy_tdx.realtime.engine.RealtimeStrategy` 拿来就能跑，不必每个
用户都手写一遍轮询循环、symbol key 拼接、asyncio 调度。

.. note::

    这是 **约 ``interval`` 秒延迟的快照轮询**，不是逐笔 tick。适合盘中信号
    提醒、轻量监控；不适合高频 / 逐笔撮合。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .engine import EventBus, EventType, MarketEvent

logger = logging.getLogger(__name__)

# Market 整数 → 字符串前缀。EventBus.publish 用 ``f"{market}{code}"`` 做 key，
# 所以这里必须产出与订阅 key 一致的字符串前缀。
_MARKET_INT_TO_STR: dict[int, str] = {0: "SZ", 1: "SH", 2: "BJ"}

# A 股常规交易时段（含集合竞价）。盘外时段默认不轮询，避免空转 + 被服务器限流。
_DEFAULT_SESSIONS: tuple[tuple[int, int], ...] = (
    (9 * 60 + 15, 11 * 60 + 30),  # 09:15 - 11:30（含集合竞价）
    (13 * 60 + 0, 15 * 60 + 0),  # 13:00 - 15:00
)

_BATCH_SIZE = 80  # get_stock_quotes 单次上限（协议约束）


def _market_int_to_str(market: int) -> str:
    """把 ``Market`` 整数转成 ``EventBus`` 用的字符串前缀。

    未知市场回退为十进制字符串，保证 ``publish`` key 可拼接、不丢事件。
    """
    return _MARKET_INT_TO_STR.get(market, str(market))


def _is_in_session(now: float, sessions: tuple[tuple[int, int], ...]) -> bool:
    """判断 ``now``（epoch 秒）的本地时分是否落在某个交易时段内。

    空 ``sessions`` 表示不做时段过滤，始终返回 True。
    """
    if not sessions:
        return True
    lt = time.localtime(now)
    minute_of_day = lt.tm_hour * 60 + lt.tm_min
    for start, end in sessions:
        if start <= minute_of_day < end:
            return True
    return False


def _row_to_event(row: pd.Series, timestamp: float) -> MarketEvent | None:
    """把 quotes DataFrame 的一行转成 :class:`MarketEvent`。

    - ``market`` 列是 int，转成字符串前缀以匹配 ``EventBus.publish`` 的 key。
    - 最新价取 ``close`` 列（``get_stock_quotes`` 没有 ``price`` 列，最新成交价
      落在 ``close``）。
    - 缺列时回退为 0.0，保证事件仍可发布。
    """
    code = str(row.get("code", ""))
    if not code:
        return None
    market_raw = row.get("market")
    try:
        market_int = int(market_raw)
    except (TypeError, ValueError):
        market_int = -1
    market_str = _market_int_to_str(market_int)

    def _f(key: str) -> float:
        try:
            return float(row.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return MarketEvent(
        event_type=EventType.TICK,
        code=code,
        market=market_str,
        price=_f("close"),
        volume=_f("vol"),
        timestamp=timestamp,
        data={
            "open": _f("open"),
            "high": _f("high"),
            "low": _f("low"),
            "pre_close": _f("pre_close"),
            "amount": _f("amount"),
            "name": str(row.get("name", "")),
        },
    )


@dataclass
class _FeedState:
    """跨周期去重用的上次价格/成交量缓存。"""

    last: dict[str, tuple[float, float]] = field(default_factory=dict)

    def changed(self, key: str, price: float, volume: float) -> bool:
        prev = self.last.get(key)
        self.last[key] = (price, volume)
        return prev != (price, volume)


class RealtimeDataFeed:
    """轮询 ``get_stock_quotes`` 并把快照发布到 :class:`EventBus`。

    同时支持 **异步客户端**（推荐，:meth:`run_async`）和 **同步客户端**
    （:meth:`run_sync`，把阻塞调用丢到 executor 线程，避免卡住事件循环）。

    用法（异步，最常见）::

        from easy_tdx.mac.client import AsyncMacClient
        from easy_tdx.realtime.engine import EventBus, RealtimeStrategy
        from easy_tdx.realtime.feed import RealtimeDataFeed

        bus = EventBus()
        bus.subscribe("SZ000001", MyStrategy().on_tick)

        feed = RealtimeDataFeed(
            bus=bus,
            symbols=[(0, "000001"), (1, "600519")],  # [(Market.SZ, code), ...]
        )
        async with AsyncMacClient.from_best_host() as client:
            await feed.run_async(client)

    用法（同步客户端）::

        from easy_tdx.mac.client import MacClient

        feed = RealtimeDataFeed(bus=bus, symbols=[(0, "000001")])
        with MacClient.from_best_host() as client:
            feed.run_sync(client)  # 阻塞，直到 Ctrl+C 或 feed.stop()

    Attributes:
        bus: 目标事件总线。
        symbols: ``[(market_int, code), ...]`` 列表，单次最多 80 只（协议上限）。
        interval: 轮询间隔（秒），默认 3.0。
        dedup: 是否对 ``(price, volume)`` 未变化的标的跳过发布，默认 True。
        sessions: 交易时段（``[(start_min, end_min), ...]``，分钟数），
            盘外时段只睡眠不拉取；传空 tuple 表示不做时段过滤（全天轮询）。
        fields: 透传给 ``get_stock_quotes`` 的字段选择，默认 None 用客户端默认。
    """

    def __init__(
        self,
        bus: EventBus,
        symbols: Iterable[tuple[int, str]],
        *,
        interval: float = 3.0,
        dedup: bool = True,
        sessions: tuple[tuple[int, int], ...] | None = None,
        fields: object = None,
    ) -> None:
        symbol_list = list(symbols)
        if not symbol_list:
            raise ValueError("symbols 不能为空")
        if len(symbol_list) > _BATCH_SIZE:
            raise ValueError(
                f"symbols 最多 {_BATCH_SIZE} 只（get_stock_quotes 单次上限），"
                f"当前传了 {len(symbol_list)} 只"
            )

        self._bus = bus
        self._symbols = symbol_list
        self._interval = max(0.1, interval)
        self._dedup = dedup
        self._sessions = _DEFAULT_SESSIONS if sessions is None else sessions
        self._fields = fields
        self._state = _FeedState()
        self._running = False
        # stop() 在 run_async/run_sync 首次调度前调用的竞态防护：
        # run_* 的首行会把 _running 重置为 True，若不另立 stop 标志，
        # 「先 stop 后 start」的停止请求会被覆盖，任务永不退出
        # （RealtimeStreamHub 换标的重建 feed 时必现，v1.28 修复）。
        self._stop_requested = False

    @property
    def running(self) -> bool:
        """是否正在轮询。"""
        return self._running

    async def run_async(
        self,
        client: Any,
        *,
        max_iterations: int | None = None,
    ) -> None:
        """异步轮询循环（主推入口）。

        Args:
            client: 拥有 ``async def get_stock_quotes`` 的客户端
                （如 :class:`~easy_tdx.mac.client.AsyncMacClient`）。
            max_iterations: 最多轮询多少轮（测试用）；None 表示无限循环直到
                :meth:`stop`。
        """
        if self._stop_requested:
            return  # 启动前已请求停止（见 __init__ 的竞态说明）
        self._running = True
        try:
            count = 0
            while self._running:
                if max_iterations is not None and count >= max_iterations:
                    break
                count += 1
                await self._poll_once_async(client)
                await self._sleep_or_stop()
        finally:
            self._running = False

    def run_sync(
        self,
        client: Any,
        *,
        max_iterations: int | None = None,
    ) -> None:
        """同步轮询循环（阻塞调用方）。

        同步客户端的 ``get_stock_quotes`` 是阻塞 socket 调用，直接放进 asyncio
        事件循环会卡死整个 loop。本方法把每次拉取丢到默认 executor 线程执行，
        发布事件仍走事件循环，从而既不卡 loop、又不用换异步客户端。

        Args:
            client: 拥有同步 ``get_stock_quotes`` 的客户端
                （如 :class:`~easy_tdx.mac.client.MacClient`）。
            max_iterations: 最多轮询多少轮（测试用）。
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError(
                    "检测到正在运行的事件循环；请在循环内改用 "
                    "await feed.run_async(...) 而非 feed.run_sync(...)"
                )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._run_sync_loop(client, max_iterations))
        finally:
            if not loop.is_running():
                loop.close()

    async def _run_sync_loop(self, client: Any, max_iterations: int | None) -> None:
        """同步客户端的轮询循环：阻塞调用丢到 executor。"""
        if self._stop_requested:
            return  # 启动前已请求停止（见 __init__ 的竞态说明）
        self._running = True
        try:
            count = 0
            while self._running:
                if max_iterations is not None and count >= max_iterations:
                    break
                count += 1
                await self._poll_once_sync(client)
                await self._sleep_or_stop()
        finally:
            self._running = False

    def stop(self) -> None:
        """请求停止轮询（下一轮 sleep 结束后生效）。

        在 ``run_async`` / ``run_sync`` 首次获得调度之前调用同样有效
        （启动即退出），见 ``__init__`` 的竞态说明。
        """
        self._stop_requested = True
        self._running = False

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    async def _poll_once_async(self, client: Any) -> None:
        now = time.time()
        if not self._in_session(now):
            return
        try:
            df = await client.get_stock_quotes(self._symbols, self._fields)
        except Exception:
            logger.exception("async get_stock_quotes 失败，本轮跳过")
            return
        await self._publish_df(df, now)

    async def _poll_once_sync(self, client: Any) -> None:
        now = time.time()
        if not self._in_session(now):
            return
        loop = asyncio.get_event_loop()
        try:
            df = await loop.run_in_executor(
                None, client.get_stock_quotes, self._symbols, self._fields
            )
        except Exception:
            logger.exception("sync get_stock_quotes 失败，本轮跳过")
            return
        await self._publish_df(df, now)

    async def _publish_df(self, df: pd.DataFrame, timestamp: float) -> None:
        if df is None or df.empty:
            return
        for _, row in df.iterrows():
            event = _row_to_event(row, timestamp)
            if event is None:
                continue
            key = f"{event.market}{event.code}"
            if self._dedup and not self._state.changed(key, event.price, event.volume):
                continue
            await self._bus.publish(event)

    def _in_session(self, now: float) -> bool:
        return _is_in_session(now, self._sessions)

    async def _sleep_or_stop(self) -> None:
        """按 interval 睡眠，但每 0.5s 检查一次 stop 标志，缩短退出延迟。"""
        elapsed = 0.0
        step = 0.5
        while elapsed < self._interval and self._running:
            await asyncio.sleep(min(step, self._interval - elapsed))
            elapsed += step
