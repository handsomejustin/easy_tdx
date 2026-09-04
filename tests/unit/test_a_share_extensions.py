"""针对本轮 A 股增强功能的单元测试。"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from easy_tdx import AsyncTdxClient, Market, TdxClient
from easy_tdx.client import _classify_fund_flow
from easy_tdx.commands.minute_time import (
    GetHistoryMinuteTimeDataCmd,
)
from easy_tdx.commands.security_bars import GetIndexBarsCmd, GetSecurityBarsCmd
from easy_tdx.commands.security_list import GetSecurityListCmd
from easy_tdx.commands.security_quotes import GetSecurityQuotesCmd
from easy_tdx.commands.transaction import (
    GetHistoryTransactionDataCmd,
    GetTransactionDataCmd,
)
from easy_tdx.models.bar import SecurityBar
from easy_tdx.models.quote import SecurityQuote
from easy_tdx.models.security import SecurityInfo
from easy_tdx.models.timeseries import MinuteBar, TransactionRecord


@patch("easy_tdx.client.TdxConnection")
def test_get_fund_flow_logic(_mock_conn_cls):
    """测试资金流分类计算逻辑。"""
    client = TdxClient("127.0.0.1")

    mock_recs = [
        TransactionRecord(10, 0, 100.0, 101, 0, 0),  # super_in
        TransactionRecord(10, 1, 10.0, 250, 1, 0),  # large_out
        TransactionRecord(10, 2, 10.0, 10, 0, 0),  # small_in
    ]

    def mock_execute(cmd):
        if isinstance(cmd, GetTransactionDataCmd):
            return mock_recs
        return []

    with patch.object(TdxClient, "_execute", side_effect=mock_execute):
        flow = client.get_fund_flow(Market.SH, "600000")
        assert isinstance(flow, pd.DataFrame)
        assert flow["super_in"].iloc[0] == 1010000.0
        assert flow["large_out"].iloc[0] == 250000.0
        assert flow["small_in"].iloc[0] == 10000.0
        # 当日资金流同样物化主力净额列（Issue #52）
        assert flow["main_net_inflow"].iloc[0] == 1010000.0 - 250000.0


def test_classify_fund_flow_exact_thresholds_use_lower_bucket():
    """恰好命中阈值时，应落入较低一档。"""
    flow = _classify_fund_flow(
        [
            TransactionRecord(10, 0, 100.0, 100, 0, 0),  # 100w -> large
            TransactionRecord(10, 1, 100.0, 20, 0, 0),  # 20w -> medium
            TransactionRecord(10, 2, 100.0, 4, 0, 0),  # 4w -> small
        ]
    )

    assert flow.super_in == 0.0
    assert flow.large_in == 1000000.0
    assert flow.medium_in == 200000.0
    assert flow.small_in == 40000.0


@patch("easy_tdx.client.TdxConnection")
def test_get_security_list_all_filtering(_mock_conn_cls):
    """测试三市 A 股过滤与行业挂载逻辑。"""
    client = TdxClient("127.0.0.1")

    industry_cfg = b"1|600000|T01|||X01\n0|000001|T02|||X02\n2|830000|T03|||X03"

    def mock_execute(cmd):
        if isinstance(cmd, GetSecurityListCmd):
            if cmd.market == Market.SH:
                return [
                    SecurityInfo(Market.SH, "600000", "SH_A", 100, 2, 10.0),
                    SecurityInfo(Market.SH, "999999", "INDEX", 100, 2, 3000.0),
                ]
            if cmd.market == Market.SZ:
                return [SecurityInfo(Market.SZ, "000001", "SZ_A", 100, 2, 10.0)]
            return []
        return []

    with (
        patch.object(TdxClient, "_execute", side_effect=mock_execute),
        patch.object(TdxClient, "get_report_file", return_value=industry_cfg),
        patch.object(TdxClient, "get_security_count", return_value=1),
    ):
        all_stocks = client.get_security_list_all(pages=1)

        assert isinstance(all_stocks, pd.DataFrame)
        assert len(all_stocks) == 2
        codes = all_stocks["code"].tolist()
        assert "600000" in codes
        assert "000001" in codes
        assert "830000" not in codes
        row = all_stocks[all_stocks["code"] == "600000"].iloc[0]
        assert row["industry_tdx"] == "T01"


@patch("easy_tdx.client.TdxConnection")
def test_get_market_stat_mapping(_mock_conn_cls):
    """测试市场统计字段映射。

    通达信统计指数的计数字段返回真实家数的 1/10，get_market_stat 内部需 ×10 还原。
    这里构造的原始协议值是还原后家数的 1/10，断言还原后等于真实家数。
    """
    client = TdxClient("127.0.0.1")

    def _zero_quote(code, **kw):
        """构造一只仅关键字段非零的 SecurityQuote，其余五档/活跃度字段取默认 0。"""
        base = dict(
            price=0,
            pre_close=0,
            open=0,
            high=0,
            low=0,
            vol=0,
            cur_vol=0,
            amount=0,
            s_vol=0,
            b_vol=0,
            active1=0,
            active2=0,
            bid1=0,
            bid_vol1=0,
            bid2=0,
            bid_vol2=0,
            bid3=0,
            bid_vol3=0,
            bid4=0,
            bid_vol4=0,
            bid5=0,
            bid_vol5=0,
            ask1=0,
            ask_vol1=0,
            ask2=0,
            ask_vol2=0,
            ask3=0,
            ask_vol3=0,
            ask4=0,
            ask_vol4=0,
            ask5=0,
            ask_vol5=0,
            rise_speed=0,
            limit_up=0,
            limit_down=0,
        )
        base.update(kw)
        return SecurityQuote(Market.SH, code, **base)

    # 880005: 计数字段=真实家数/10；amount/vol 不缩放，原样透传
    q_stat = _zero_quote(
        "880005",
        price=300.0,  # up   = 300 * 10 = 3000
        open=200.0,  # down = 200 * 10 = 2000
        high=550.0,  # total= 550 * 10 = 5500
        low=50.0,  # neutral = 50 * 10 = 500
        vol=1000000.0,
        amount=50000000.0,
    )
    # 880001: 总市值指数点位（不缩放）
    q_cap = _zero_quote("880001", price=1186.579)
    # 880006: 涨跌停家数=真实/10
    q_limit = _zero_quote(
        "880006",
        price=13.1,  # limit_up   = 131
        open=0.6,  # limit_down = 6
    )

    def mock_execute(cmd):
        if isinstance(cmd, GetSecurityQuotesCmd):
            return [q_stat, q_cap, q_limit]
        return []

    with patch.object(TdxClient, "_execute", side_effect=mock_execute):
        stat = client.get_market_stat()
        assert isinstance(stat, pd.DataFrame)
        # 计数字段 ×10 还原
        assert stat["up_count"].iloc[0] == 3000
        assert stat["down_count"].iloc[0] == 2000
        assert stat["neutral_count"].iloc[0] == 500
        assert stat["total_count"].iloc[0] == 5500
        assert stat["limit_up_count"].iloc[0] == 131
        assert stat["limit_down_count"].iloc[0] == 6
        # suspended = total - up - down - neutral = 5500 - 5500 = 0
        assert stat["suspended_count"].iloc[0] == 0
        # 成交额/量不缩放，原样透传
        assert stat["total_amount"].iloc[0] == 50000000.0
        assert stat["total_volume"].iloc[0] == 1000000.0
        # 总市值 = 1186.579 * 1e10
        assert stat["total_market_cap"].iloc[0] == 1186.579 * 1e10


@patch("easy_tdx.client.TdxConnection")
def test_get_history_fund_flow_fallback(_mock_conn_cls):
    """资金流由日K取日期 + 历史逐笔重算；返回含 main_net_inflow 列。"""
    client = TdxClient("127.0.0.1")

    bars = [
        SecurityBar(10, 10, 10, 10, 0, 0, 2025, 1, 8, 15, 0),
        SecurityBar(10, 10, 10, 10, 0, 0, 2025, 1, 9, 15, 0),
    ]
    txn_map = {
        20250108: [
            TransactionRecord(10, 0, 100.0, 101, 0, 0),
            TransactionRecord(10, 1, 10.0, 250, 1, 0),
        ],
        20250109: [
            TransactionRecord(10, 0, 10.0, 10, 0, 0),
        ],
    }

    def mock_execute(cmd):
        if isinstance(cmd, GetSecurityBarsCmd):
            return bars
        if isinstance(cmd, GetHistoryTransactionDataCmd):
            if cmd.start > 0:
                return []
            return txn_map.get(cmd.date, [])
        return []

    with patch.object(TdxClient, "_execute", side_effect=mock_execute):
        flows = client.get_history_fund_flow(Market.SH, "600000", 0, 2)

    assert isinstance(flows, pd.DataFrame)
    assert len(flows) == 2
    # 主力净额列必须存在（Issue #52：asdict 丢弃 property 导致此前无此列）
    assert "main_net_inflow" in flows.columns
    assert flows.columns[1] == "main_net_inflow"
    row0 = flows.iloc[0]
    assert row0["super_in"] == 1010000.0
    assert row0["large_out"] == 250000.0
    assert row0["main_net_inflow"] == (1010000.0 + 0.0) - (0.0 + 250000.0)
    row1 = flows.iloc[1]
    assert row1["small_in"] == 10000.0
    # 仅小单流入，不计入主力净额
    assert row1["main_net_inflow"] == 0.0


@patch("easy_tdx.client.TdxConnection")
def test_get_history_fund_flow_today_uses_realtime_ticks(_mock_conn_cls):
    """当日 bar 盘中取当日实时逐笔（Issue #52：历史逐笔当日恒空致整行为 0）。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))

    client = TdxClient("127.0.0.1")
    yesterday = now - timedelta(days=1)
    bars = [
        # 顺序与服务器一致：旧 → 新，最新一根是今天
        SecurityBar(10, 10, 10, 10, 0, 0, yesterday.year, yesterday.month, yesterday.day, 15, 0),
        SecurityBar(10, 10, 10, 10, 0, 0, now.year, now.month, now.day, 15, 0),
    ]
    history_txn = {
        yesterday.year * 10000 + yesterday.month * 100 + yesterday.day: [
            TransactionRecord(10, 0, 10.0, 10, 0, 0)
        ]
    }
    realtime_txn = [TransactionRecord(13, 0, 100.0, 101, 0, 0)]

    seen_cmds = []

    def mock_execute(cmd):
        seen_cmds.append(type(cmd).__name__)
        if isinstance(cmd, GetSecurityBarsCmd):
            return bars
        if isinstance(cmd, GetTransactionDataCmd):
            if cmd.start > 0:
                return []
            return realtime_txn
        if isinstance(cmd, GetHistoryTransactionDataCmd):
            if cmd.start > 0:
                return []
            return history_txn.get(cmd.date, [])
        return []

    with patch.object(TdxClient, "_execute", side_effect=mock_execute):
        flows = client.get_history_fund_flow(Market.SH, "600000", 0, 2)

    assert len(flows) == 2
    assert "GetTransactionDataCmd" in seen_cmds
    today_row = flows.iloc[-1]
    # 今日行来自实时逐笔：100 元 × 101 手 × 100 = 超大单流入 1010000
    assert today_row["super_in"] == 1010000.0
    assert today_row["main_net_inflow"] == 1010000.0
    # 昨日行来自历史逐笔：小单流入 10000
    assert flows.iloc[0]["small_in"] == 10000.0


@patch("easy_tdx.client.TdxConnection")
def test_get_price_limits_uses_listing_window(_mock_conn_cls):
    """client.get_price_limits 应结合日 K 条数判断上市初期限价窗口。"""
    client = TdxClient("127.0.0.1")

    def mock_execute_5(cmd):
        if isinstance(cmd, GetSecurityBarsCmd):
            return [SecurityBar(0, 0, 0, 0, 0, 0, 2025, 1, 1, 15, 0)] * 5
        return []

    with patch.object(TdxClient, "_execute", side_effect=mock_execute_5):
        assert client.get_price_limits(Market.SH, "600001", "主板新股", 10.0) == (
            None,
            None,
        )

    def mock_execute_6(cmd):
        if isinstance(cmd, GetSecurityBarsCmd):
            return [SecurityBar(0, 0, 0, 0, 0, 0, 2025, 1, 1, 15, 0)] * 6
        return []

    with patch.object(TdxClient, "_execute", side_effect=mock_execute_6):
        assert client.get_price_limits(Market.SH, "600001", "主板老股", 10.0) == (
            11.0,
            9.0,
        )


@patch("easy_tdx.client.TdxConnection")
def test_get_minute_time_data_intraday_uses_history_today(_mock_conn_cls):
    """盘中（最新日K=今天）：历史分时接口对当日即返回已成交分钟，只查今天一次。"""
    client = TdxClient("127.0.0.1")
    day_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 2026, 9, 4, 15, 0)]
    expected = [MinuteBar(price=44.2, vol=118)]

    def mock_execute(cmd):
        if isinstance(cmd, GetSecurityBarsCmd):
            return day_bars
        if isinstance(cmd, GetHistoryMinuteTimeDataCmd):
            assert cmd.date == 20260904, "盘中应只查今天的历史分时"
            return expected
        return []

    with (
        patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
        patch.object(TdxClient, "_execute", side_effect=mock_execute) as mock_exec,
    ):
        result = client.get_minute_time_data(Market.SH, "600000")

    assert isinstance(result, pd.DataFrame)
    assert result["price"].iloc[0] == 44.2
    assert str(result["datetime"].iloc[0]).startswith("2026-09-04")
    history_calls = [
        c for c in mock_exec.call_args_list if isinstance(c[0][0], GetHistoryMinuteTimeDataCmd)
    ]
    assert len(history_calls) == 1


@patch("easy_tdx.client.TdxConnection")
def test_get_minute_time_data_preopen_falls_back_to_last_trade_day(_mock_conn_cls):
    """盘前/周末/节假日：今日分时尚不存在（历史分时当日返回空），回退最近交易日。"""
    client = TdxClient("127.0.0.1")
    day_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 2026, 9, 3, 15, 0)]
    expected = [MinuteBar(price=40.91, vol=3677)]

    def mock_execute(cmd):
        if isinstance(cmd, GetSecurityBarsCmd):
            return day_bars
        if isinstance(cmd, GetHistoryMinuteTimeDataCmd):
            return expected if cmd.date == 20260903 else []
        return []

    with (
        patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
        patch.object(TdxClient, "_execute", side_effect=mock_execute),
    ):
        result = client.get_minute_time_data(Market.SH, "600000")

    assert result["price"].iloc[0] == 40.91
    assert str(result["datetime"].iloc[0]).startswith("2026-09-03")


@patch("easy_tdx.client.TdxConnection")
def test_get_minute_time_data_no_daily_bars_keeps_old_contract(_mock_conn_cls):
    """兜底：无日 K 数据（未上市新股等）时维持旧契约——查今日历史分时。"""
    client = TdxClient("127.0.0.1")

    with (
        patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
        patch.object(TdxClient, "_execute", return_value=[]),
        patch.object(TdxClient, "_find_host_returning_data", return_value=[]),
    ):
        result = client.get_minute_time_data(Market.SH, "600000")

    assert isinstance(result, pd.DataFrame)
    assert result.empty


@patch("easy_tdx.client.TdxConnection")
def test_get_minute_time_data_index_anchor_uses_index_bars(_mock_conn_cls):
    """指数：个股K线命令对指数返回乱码日期，锚点应换指数K线命令取最近交易日。"""
    client = TdxClient("127.0.0.1")
    garbage_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 11678, 5, 68, 15, 0)]
    index_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 2026, 9, 3, 15, 0)]
    expected = [MinuteBar(price=3350.5, vol=100000)]

    def mock_execute(cmd):
        if isinstance(cmd, GetIndexBarsCmd):  # 子类必须先判，否则会被个股分支截胡
            return index_bars
        if isinstance(cmd, GetSecurityBarsCmd):
            return garbage_bars
        if isinstance(cmd, GetHistoryMinuteTimeDataCmd):
            return expected if cmd.date == 20260903 else []
        return []

    with (
        patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
        patch.object(TdxClient, "_execute", side_effect=mock_execute),
    ):
        result = client.get_minute_time_data(Market.SH, "000001")

    assert result["price"].iloc[0] == 3350.5
    assert str(result["datetime"].iloc[0]).startswith("2026-09-03")


def test_async_get_minute_time_data_index_anchor_uses_index_bars():
    """异步客户端：指数锚点走指数K线命令。"""
    garbage_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 11678, 5, 68, 15, 0)]
    index_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 2026, 9, 3, 15, 0)]
    expected = [MinuteBar(price=3350.5, vol=100000)]

    async def run_test() -> None:
        with patch("easy_tdx.client.AsyncTdxConnection"):
            client = AsyncTdxClient("127.0.0.1")

            async def mock_execute(cmd):
                if isinstance(cmd, GetIndexBarsCmd):
                    return index_bars
                if isinstance(cmd, GetSecurityBarsCmd):
                    return garbage_bars
                if isinstance(cmd, GetHistoryMinuteTimeDataCmd):
                    return expected if cmd.date == 20260903 else []
                return []

            with (
                patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
                patch.object(AsyncTdxClient, "_execute", side_effect=mock_execute),
            ):
                result = await client.get_minute_time_data(Market.SH, "000001")

            assert result["price"].iloc[0] == 3350.5
            assert str(result["datetime"].iloc[0]).startswith("2026-09-03")

    asyncio.run(run_test())


def test_async_get_minute_time_data_preopen_falls_back_to_last_trade_day():
    """异步客户端：盘前回退最近交易日历史分时。"""
    day_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 2026, 9, 3, 15, 0)]
    expected = [MinuteBar(price=40.91, vol=3677)]

    async def run_test() -> None:
        with patch("easy_tdx.client.AsyncTdxConnection"):
            client = AsyncTdxClient("127.0.0.1")

            async def mock_execute(cmd):
                if isinstance(cmd, GetSecurityBarsCmd):
                    return day_bars
                if isinstance(cmd, GetHistoryMinuteTimeDataCmd):
                    return expected if cmd.date == 20260903 else []
                return []

            with (
                patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
                patch.object(AsyncTdxClient, "_execute", side_effect=mock_execute),
            ):
                result = await client.get_minute_time_data(Market.SH, "600000")

            assert result["price"].iloc[0] == 40.91
            assert str(result["datetime"].iloc[0]).startswith("2026-09-03")

    asyncio.run(run_test())


def test_async_get_minute_time_data_intraday_uses_history_today():
    """异步客户端：盘中走历史分时接口查今天。"""
    day_bars = [SecurityBar(10, 10, 10, 10, 100, 1000, 2026, 9, 4, 15, 0)]
    expected = [MinuteBar(price=44.2, vol=118)]

    async def run_test() -> None:
        with patch("easy_tdx.client.AsyncTdxConnection"):
            client = AsyncTdxClient("127.0.0.1")

            async def mock_execute(cmd):
                if isinstance(cmd, GetSecurityBarsCmd):
                    return day_bars
                if isinstance(cmd, GetHistoryMinuteTimeDataCmd):
                    assert cmd.date == 20260904, "盘中应只查今天的历史分时"
                    return expected
                return []

            with (
                patch("easy_tdx.client._today_in_shanghai", return_value=20260904),
                patch.object(AsyncTdxClient, "_execute", side_effect=mock_execute),
            ):
                result = await client.get_minute_time_data(Market.SH, "600000")

            assert result["price"].iloc[0] == 44.2

    asyncio.run(run_test())
