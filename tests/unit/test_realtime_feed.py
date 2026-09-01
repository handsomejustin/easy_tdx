"""单元测试：RealtimeDataFeed 轮询数据源."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from easy_tdx.realtime.engine import EventBus, EventType, MarketEvent
from easy_tdx.realtime.feed import (
    RealtimeDataFeed,
    _is_in_session,
    _market_int_to_str,
    _row_to_event,
)

# ── 测试数据 ────────────────────────────────────────────────────────────


def _sample_quotes_df() -> pd.DataFrame:
    """模拟 get_stock_quotes 返回的 DataFrame。

    列结构与 MacClient._quotes_to_df 一致：market(int) / code / name + 字段。
    """
    return pd.DataFrame(
        [
            {
                "market": 0,  # SZ
                "code": "000001",
                "name": "平安银行",
                "close": 10.50,
                "vol": 100000,
                "open": 10.30,
                "high": 10.60,
                "low": 10.20,
                "pre_close": 10.40,
                "amount": 1050000.0,
            },
            {
                "market": 1,  # SH
                "code": "600519",
                "name": "贵州茅台",
                "close": 1800.0,
                "vol": 5000,
                "open": 1790.0,
                "high": 1810.0,
                "low": 1785.0,
                "pre_close": 1795.0,
                "amount": 9000000.0,
            },
        ]
    )


class AsyncMockClient:
    """模拟异步客户端：按预设序列返回 DataFrame。"""

    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self._frames = frames
        self._idx = 0
        self.calls: list[list[tuple[int, str]]] = []

    async def get_stock_quotes(
        self, stocks: list[tuple[int, str]], fields: object = None
    ) -> pd.DataFrame:
        self.calls.append(list(stocks))
        if self._idx < len(self._frames):
            df = self._frames[self._idx]
            self._idx += 1
            return df
        return pd.DataFrame()


class SyncMockClient:
    """模拟同步客户端。"""

    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self._frames = frames
        self._idx = 0
        self.calls: list[list[tuple[int, str]]] = []

    def get_stock_quotes(
        self, stocks: list[tuple[int, str]], fields: object = None
    ) -> pd.DataFrame:
        self.calls.append(list(stocks))
        if self._idx < len(self._frames):
            df = self._frames[self._idx]
            self._idx += 1
            return df
        return pd.DataFrame()


# ── 纯函数测试 ──────────────────────────────────────────────────────────


class TestMarketIntToStr:
    def test_known_markets(self) -> None:
        assert _market_int_to_str(0) == "SZ"
        assert _market_int_to_str(1) == "SH"
        assert _market_int_to_str(2) == "BJ"

    def test_unknown_falls_back(self) -> None:
        assert _market_int_to_str(99) == "99"


class TestIsInSession:
    def test_in_morning_session(self) -> None:
        # 构造一个 10:30 的 epoch（任意日期，tm_hour=10, tm_min=30）
        t = time.mktime(time.strptime("2026-07-13 10:30:00", "%Y-%m-%d %H:%M:%S"))
        sessions = ((9 * 60 + 15, 11 * 60 + 30), (13 * 60, 15 * 60))
        assert _is_in_session(t, sessions) is True

    def test_outside_session(self) -> None:
        t = time.mktime(time.strptime("2026-07-13 08:00:00", "%Y-%m-%d %H:%M:%S"))
        sessions = ((9 * 60 + 15, 11 * 60 + 30), (13 * 60, 15 * 60))
        assert _is_in_session(t, sessions) is False

    def test_empty_sessions_always_in(self) -> None:
        t = time.mktime(time.strptime("2026-07-13 03:00:00", "%Y-%m-%d %H:%M:%S"))
        assert _is_in_session(t, ()) is True


class TestRowToEvent:
    def test_basic_conversion(self) -> None:
        df = _sample_quotes_df()
        event = _row_to_event(df.iloc[0], timestamp=1700000000.0)
        assert event is not None
        assert event.code == "000001"
        assert event.market == "SZ"
        assert event.price == 10.50
        assert event.volume == 100000
        assert event.event_type == EventType.TICK
        assert event.data["name"] == "平安银行"
        assert event.data["pre_close"] == 10.40

    def test_sh_market_prefix(self) -> None:
        df = _sample_quotes_df()
        event = _row_to_event(df.iloc[1], timestamp=0.0)
        assert event is not None
        assert event.market == "SH"
        assert event.code == "600519"
        assert event.price == 1800.0

    def test_missing_columns_default_zero(self) -> None:
        row = pd.Series({"code": "000002", "market": 0, "name": "万科A"})
        event = _row_to_event(row, timestamp=0.0)
        assert event is not None
        assert event.price == 0.0
        assert event.volume == 0.0

    def test_empty_code_returns_none(self) -> None:
        row = pd.Series({"code": "", "market": 0})
        assert _row_to_event(row, timestamp=0.0) is None


# ── Feed 构造测试 ───────────────────────────────────────────────────────


class TestFeedConstruction:
    def test_empty_symbols_raises(self) -> None:
        with pytest.raises(ValueError, match="不能为空"):
            RealtimeDataFeed(bus=EventBus(), symbols=[])

    def test_too_many_symbols_raises(self) -> None:
        symbols = [(0, f"{i:06d}") for i in range(81)]
        with pytest.raises(ValueError, match="80"):
            RealtimeDataFeed(bus=EventBus(), symbols=symbols)

    def test_interval_clamped_to_minimum(self) -> None:
        feed = RealtimeDataFeed(bus=EventBus(), symbols=[(0, "000001")], interval=0.01)
        assert feed._interval == 0.1

    def test_sessions_override_empty(self) -> None:
        feed = RealtimeDataFeed(bus=EventBus(), symbols=[(0, "000001")], sessions=())
        # 空 sessions → _in_session 始终 True
        assert feed._in_session(0.0) is True


# ── 异步 publish 路径测试 ───────────────────────────────────────────────


class TestAsyncPublishPath:
    async def test_events_published_to_correct_keys(self) -> None:
        """关键测试：market int 0 → 'SZ'，订阅 'SZ000001' 必须收到。"""
        bus = EventBus()
        received: list[MarketEvent] = []
        bus.subscribe("SZ000001", lambda e: received.append(e))
        bus.subscribe("SH600519", lambda e: received.append(e))

        client = AsyncMockClient([_sample_quotes_df()])
        feed = RealtimeDataFeed(
            bus=bus,
            symbols=[(0, "000001"), (1, "600519")],
            sessions=(),  # 测试不受时段限制
            interval=0.1,
        )
        await feed.run_async(client, max_iterations=1)

        assert len(received) == 2
        codes = {e.code for e in received}
        assert codes == {"000001", "600519"}
        # symbol key 必须匹配：SZ 前缀
        sz_event = next(e for e in received if e.code == "000001")
        assert sz_event.market == "SZ"
        assert sz_event.price == 10.50

    async def test_dedup_skips_unchanged(self) -> None:
        bus = EventBus()
        received: list[MarketEvent] = []
        bus.subscribe_all(lambda e: received.append(e))

        same_df = _sample_quotes_df()
        client = AsyncMockClient([same_df.copy(), same_df.copy()])
        feed = RealtimeDataFeed(
            bus=bus,
            symbols=[(0, "000001"), (1, "600519")],
            dedup=True,
            sessions=(),
            interval=0.1,
        )
        await feed.run_async(client, max_iterations=2)

        # 第一轮 2 个事件，第二轮因 price/volume 不变被去重
        assert len(received) == 2

    async def test_dedup_disabled_publishes_all(self) -> None:
        bus = EventBus()
        received: list[MarketEvent] = []
        bus.subscribe_all(lambda e: received.append(e))

        same_df = _sample_quotes_df()
        client = AsyncMockClient([same_df.copy(), same_df.copy()])
        feed = RealtimeDataFeed(
            bus=bus,
            symbols=[(0, "000001"), (1, "600519")],
            dedup=False,
            sessions=(),
            interval=0.1,
        )
        await feed.run_async(client, max_iterations=2)

        assert len(received) == 4

    async def test_empty_df_publishes_nothing(self) -> None:
        bus = EventBus()
        received: list[MarketEvent] = []
        bus.subscribe_all(lambda e: received.append(e))

        client = AsyncMockClient([pd.DataFrame()])
        feed = RealtimeDataFeed(bus=EventBus(), symbols=[(0, "000001")], sessions=(), interval=0.1)
        # 用 subscribe_all 的 bus
        feed._bus = bus
        await feed.run_async(client, max_iterations=1)
        assert received == []

    async def test_client_error_does_not_crash(self) -> None:
        """get_stock_quotes 抛异常时，feed 应跳过该轮，不崩溃。"""
        bus = EventBus()
        received: list[MarketEvent] = []
        bus.subscribe_all(lambda e: received.append(e))

        failing_client = MagicMock()
        failing_client.get_stock_quotes = MagicMock(side_effect=ConnectionError("boom"))

        feed = RealtimeDataFeed(bus=bus, symbols=[(0, "000001")], sessions=(), interval=0.1)
        # 不应抛异常
        await feed.run_async(failing_client, max_iterations=1)
        assert received == []


class TestSessionGating:
    async def test_outside_session_no_fetch(self) -> None:
        """盘外时段不应调用 get_stock_quotes。"""
        bus = EventBus()
        client = AsyncMockClient([_sample_quotes_df()])

        # 动态构造一个「永远在未来」的 1 分钟时段，保证当前时刻必在盘外。
        # 此前用固定 23:00-23:59 模拟盘外——测试跑在当地 23 点档时必炸
        # （时间相关 flaky）。
        _now = datetime.now()
        now_min = _now.hour * 60 + _now.minute
        feed = RealtimeDataFeed(
            bus=bus,
            symbols=[(0, "000001")],
            sessions=(((now_min + 5) % (24 * 60), (now_min + 6) % (24 * 60)),),
            interval=0.1,
        )
        await feed.run_async(client, max_iterations=1)
        assert len(client.calls) == 0  # 盘外，没拉数据


class TestStopFlag:
    async def test_stop_terminates_loop(self) -> None:
        bus = EventBus()
        client = AsyncMockClient([_sample_quotes_df()])
        feed = RealtimeDataFeed(bus=bus, symbols=[(0, "000001")], sessions=(), interval=0.2)

        # 在短延迟后请求停止
        async def _stop_soon() -> None:
            await asyncio.sleep(0.15)
            feed.stop()

        await asyncio.gather(feed.run_async(client), _stop_soon())
        assert feed.running is False
