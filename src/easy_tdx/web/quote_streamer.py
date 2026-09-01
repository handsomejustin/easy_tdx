"""实时行情 SSE 推送器：单一共享轮询循环 + 每连接独立队列 fan-out。

架构（借鉴 tick-stock-panel 的成熟模式，见其 QuoteService / SSE 演进）：

- 通达信协议是请求-响应式，没有服务端推送；"实时"本质是后端定时轮询。
- 所有 SSE 连接共享**一条**轮询循环（避免 N 个标签页 = N 倍行情请求），
  每个连接持有独立的 :class:`asyncio.Queue`，消息 fan-out 投递。
- 背压策略：队列满（说明该连接消费慢/挂起）时丢弃最旧消息、保最新——
  行情场景下旧快照无价值，宁可跳帧不可积压。
- 订阅集合 = 固定指数 + 全部自选（每次轮询前重读 watchlist，SQLite 单文件
  读极快）。前端加自选后，下一个轮询周期自动纳入推送，无需重连 SSE。
- 无人订阅时循环休眠，不产生行情请求。
- 交易时段（沪时区 09:10-15:10）~8s 一拍，其余时段降到 60s（收盘价仍可推）。
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any

import pandas as pd

from easy_tdx.models.enums import Market

logger = logging.getLogger(__name__)

__all__ = ["QuoteStreamer", "INDEX_SYMBOLS", "INDEX_NAMES"]

# 看板常驻指数（标准协议行情，指数与个股同一接口）。
INDEX_SYMBOLS: list[tuple[Market, str]] = [
    (Market.SH, "000001"),  # 上证指数
    (Market.SZ, "399001"),  # 深证成指
    (Market.SZ, "399006"),  # 创业板指
    (Market.SH, "000688"),  # 科创50
    (Market.SH, "000300"),  # 沪深300
]
INDEX_NAMES: dict[str, str] = {
    "SH000001": "上证指数",
    "SZ399001": "深证成指",
    "SZ399006": "创业板指",
    "SH000688": "科创50",
    "SH000300": "沪深300",
}

_MARKET_NAMES = {Market.SZ: "SZ", Market.SH: "SH", Market.BJ: "BJ"}

# 推送给前端的字段白名单（SecurityQuote 全字段中挑展示需要的，避免 unknown_* 噪音）。
_QUOTE_FIELDS = (
    [
        "market",
        "code",
        "price",
        "pre_close",
        "open",
        "high",
        "low",
        "vol",
        "cur_vol",
        "amount",
        "s_vol",
        "b_vol",
        "rise_speed",
        "limit_up",
        "limit_down",
        "decimal_point",
        "server_time",
        "trading_status",
    ]
    + [f"{side}{i}" for side in ("bid", "ask") for i in range(1, 6)]
    + [f"{side}_vol{i}" for side in ("bid", "ask") for i in range(1, 6)]
)

_SH_TZ = dt_timezone(timedelta(hours=8))  # Asia/Shanghai


def _is_trading_hours(now: datetime | None = None) -> bool:
    """A股盘中（含集合竞价与收盘前后缓冲）：沪时间 09:10-15:10，周一至周五。"""
    t = now or datetime.now(_SH_TZ)
    if t.weekday() >= 5:
        return False
    hm = t.hour * 60 + t.minute
    return 9 * 60 + 10 <= hm <= 15 * 60 + 10


class QuoteStreamer:
    """共享轮询 + fan-out。由 FastAPI lifespan 启停（``app.state.quote_streamer``）。

    Args:
        quote_fetcher: async ``(stocks) -> pd.DataFrame``，通常为
            ``AsyncTdxClient.get_security_quotes`` 的偏函数。异常由本类兜底。
        watch_symbols: async ``() -> list[tuple[Market, str]]``，自选订阅集合
            （通常读 :class:`WatchlistStore`）。每次轮询前调用。
        trading_interval: 盘中轮询间隔（秒）。
        idle_interval: 盘外轮询间隔（秒）。
    """

    def __init__(
        self,
        quote_fetcher: Callable[[list[tuple[Market, str]]], Awaitable[pd.DataFrame]],
        watch_symbols: Callable[[], Awaitable[list[tuple[Market, str]]]],
        *,
        trading_interval: float = 8.0,
        idle_interval: float = 60.0,
    ) -> None:
        self._fetch = quote_fetcher
        self._watch_symbols = watch_symbols
        self._trading_interval = trading_interval
        self._idle_interval = idle_interval
        self._queues: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._ids = itertools.count(1)
        self._task: asyncio.Task[None] | None = None
        self.last_snapshot: list[dict[str, Any]] = []  # 最近一次成功快照（调试/健康检查）

    # ── 订阅管理（SSE 端点调用） ──────────────────────────────────────────

    def subscribe(self) -> tuple[int, asyncio.Queue[dict[str, Any]]]:
        """注册一个独立队列；返回 (id, queue)。"""
        qid = next(self._ids)
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
        self._queues[qid] = q
        return qid, q

    def unsubscribe(self, qid: int) -> None:
        self._queues.pop(qid, None)

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    # ── 生命周期 ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())
            logger.info("QuoteStreamer started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("QuoteStreamer stopped")

    # ── 轮询主循环 ────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while True:
            try:
                if not self._queues:
                    await asyncio.sleep(1.0)  # 无人订阅，待命
                    continue

                symbols = list(INDEX_SYMBOLS)
                try:
                    symbols += await self._watch_symbols()
                except Exception:
                    logger.warning("读取自选订阅集合失败", exc_info=True)

                quotes = await self._fetch_quotes(symbols)
                if quotes:
                    self.last_snapshot = quotes
                    msg = {
                        "type": "quotes_updated",
                        "ts": datetime.now(_SH_TZ).isoformat(timespec="seconds"),
                        "count": len(quotes),
                        "quotes": quotes,
                    }
                    self._fan_out(msg)

                interval = self._trading_interval if _is_trading_hours() else self._idle_interval
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 单轮失败不能杀死循环（行情服务器闪断很常见）
                logger.warning("QuoteStreamer 轮询异常", exc_info=True)
                await asyncio.sleep(self._idle_interval)

    async def _fetch_quotes(self, symbols: list[tuple[Market, str]]) -> list[dict[str, Any]]:
        """批量拉行情（80/批），转精简 dict 列表；失败返回空。"""
        out: list[dict[str, Any]] = []
        for i in range(0, len(symbols), 80):
            batch = symbols[i : i + 80]
            try:
                df = await self._fetch(batch)
            except Exception:
                logger.warning("行情拉取失败（%d 只）", len(batch), exc_info=True)
                continue
            out.extend(self._df_to_dicts(df))
        return out

    @staticmethod
    def _df_to_dicts(df: pd.DataFrame) -> list[dict[str, Any]]:
        """DataFrame → 前端 dict（白名单列 + market 枚举转字符串 + symbol 键）。"""
        if df is None or df.empty:
            return []
        rows: list[dict[str, Any]] = []
        for rec in df.to_dict(orient="records"):
            market = rec.get("market")
            market_str = _MARKET_NAMES.get(market, str(market or ""))
            code = str(rec.get("code", ""))
            d: dict[str, Any] = {}
            for f in _QUOTE_FIELDS:
                if f in rec and f not in ("market", "code"):
                    v = rec[f]
                    d[f] = None if v != v else v  # NaN → None（JSON 合法）
            d["market"] = market_str
            d["code"] = code
            d["symbol"] = f"{market_str}{code}"
            rows.append(d)
        return rows

    def _fan_out(self, msg: dict[str, Any]) -> None:
        for q in list(self._queues.values()):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # 背压：丢最旧、保最新
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass
