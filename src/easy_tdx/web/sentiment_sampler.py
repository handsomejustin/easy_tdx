"""市场情绪采样器（交易时段每分钟落一条全市场广度快照）。

模式对齐 :class:`easy_tdx.web.quote_streamer.QuoteStreamer`：

- 后台 asyncio 任务，``start()`` 启动 / ``stop()`` 取消，进程生命周期由
  :mod:`easy_tdx.web.app` 的 lifespan 管理。
- 仅在 :func:`easy_tdx.realtime.session.is_trading_time` 内采样（盘外采样
  只会产生重复的静止快照，浪费且污染"当日分钟曲线"）。
- 采样失败静默跳过（计数告警日志），绝不中断循环——情绪曲线缺失几个点
  远好于采样器罢工。
- 写入经 :class:`easy_tdx.web.sentiment_store.SentimentStore`，(date, minute)
  幂等主键，重复采样只覆盖不累积。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from easy_tdx.realtime.session import is_trading_time
from easy_tdx.web.sentiment_store import SentimentStore, get_sentiment_store

logger = logging.getLogger(__name__)

__all__ = ["SentimentSampler"]


class SentimentSampler:
    """交易时段全市场广度采样器。"""

    def __init__(
        self,
        client_get_stat: Any,
        store: SentimentStore | None = None,
        interval: float = 60.0,
    ):
        """
        Args:
            client_get_stat: 异步可调用（``AsyncTdxClient.get_market_stat``），
                返回含 up_count/limit_up_count 等列的单行 DataFrame。
            store: 情绪存储，None 则取进程级单例。
            interval: 采样间隔（秒）。E2E mock 可调小。
        """
        self._get_stat = client_get_stat
        self._store = store or get_sentiment_store()
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self.samples = 0
        self.failures = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        logger.info("SentimentSampler 启动（间隔 %ss，仅交易时段）", self._interval)
        while True:
            try:
                if is_trading_time():
                    await self._sample_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — 采样器永不退出
                self.failures += 1
                logger.warning("情绪采样失败（累计 %d 次）", self.failures, exc_info=True)
            await asyncio.sleep(self._interval)

    async def _sample_once(self) -> None:
        df = await self._get_stat()
        if df is None or df.empty:
            raise RuntimeError("get_market_stat 返回空数据")
        row = df.iloc[0]
        now = datetime.now()
        self._store.insert(
            {
                "date": now.year * 10000 + now.month * 100 + now.day,
                "minute": now.hour * 100 + now.minute,
                "ts": int(now.timestamp()),
                "up_count": int(row.get("up_count") or 0),
                "down_count": int(row.get("down_count") or 0),
                "neutral_count": int(row.get("neutral_count") or 0),
                "total_count": int(row.get("total_count") or 0),
                "limit_up_count": int(row.get("limit_up_count") or 0),
                "limit_down_count": int(row.get("limit_down_count") or 0),
                "total_amount": float(row.get("total_amount") or 0.0),
            }
        )
        self.samples += 1


class FundFlowSampler:
    """每日收盘前记录一次行业主力净流入排行（板块资金日历数据源）。

    采样窗口：交易时段内 14:45 之后（临近收盘的净流入已基本定型），
    每日只采一次（``latest_fund_date`` 幂等）。数据走 MAC
    ``get_board_ranking(sort_by="main_net_amount")``——该实现先按涨幅
    取候选池再聚合 summary，因此口径是"涨幅前 ``top_n`` 名中主力净流入
    最高的 ``keep`` 个行业"，并非全市场严格排序（逐板块 summary 太贵）。
    """

    def __init__(
        self,
        client: Any,
        store: SentimentStore | None = None,
        interval: float = 300.0,
        top_n: int = 50,
        keep: int = 10,
    ):
        self._client = client
        self._store = store or get_sentiment_store()
        self._interval = interval
        self._top_n = top_n
        self._keep = keep
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        logger.info("FundFlowSampler 启动（间隔 %ss，交易日 14:45 后每日一条）", self._interval)
        while True:
            try:
                now = datetime.now()
                if is_trading_time(now) and (now.hour * 100 + now.minute) >= 1445:
                    await self._sample_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — 采样器永不退出
                logger.warning("板块资金采样失败", exc_info=True)
            await asyncio.sleep(self._interval)

    async def _sample_once(self) -> None:
        from easy_tdx.mac.enums import BoardType

        today = int(datetime.now().strftime("%Y%m%d"))
        if self._store.latest_fund_date() == today:
            return  # 当日已采样
        df = await self._client.get_board_ranking(
            board_type=BoardType.HY,
            top_n=self._top_n,
            sort_by="main_net_amount",
            ascending=False,
        )
        if df is None or df.empty:
            return
        ranked = df.sort_values("main_net_amount", ascending=False).head(self._keep)
        boards = [
            {
                "code": str(r["code"]),
                "name": str(r.get("name", r["code"])),
                "main_net": round(float(r["main_net_amount"]), 0),
            }
            for _, r in ranked.iterrows()
        ]
        self._store.upsert_fund_day(today, boards)
        logger.info("板块资金采样完成：%s，Top1 %s", today, boards[0]["name"] if boards else "-")
