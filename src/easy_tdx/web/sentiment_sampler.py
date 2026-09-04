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
        self._task: asyncio.Task | None = None
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
