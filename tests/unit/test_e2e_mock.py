"""E2E 合成数据源（web/e2e_mock.py）单元测试。

守护两件事：
1. mock 客户端与真实客户端的**契约**（方法签名可用、返回列覆盖前端字段）；
2. 数据的**确定性与分页语义**（E2E 断言可复现的前提）。

另有一个 TestClient 端到端用例：EASY_TDX_E2E_MOCK=1 下 /bars、/market/stat、
/mac/quote-list 返回合成数据（不连真实服务器）。
"""

from __future__ import annotations

import pandas as pd
import pytest

from easy_tdx.models.enums import Market
from easy_tdx.web.e2e_mock import (
    E2E_MOCK_ENV,
    MockMacClient,
    MockTdxClient,
    _page_bars,
    _synth_ohlcv,
)

pytest.importorskip("fastapi")


# ── 数据生成内核 ─────────────────────────────────────────────────────────────


def test_synth_ohlcv_deterministic() -> None:
    """同一 (market, code) 两次生成结果逐位一致（E2E 断言可复现的前提）。"""
    a = _synth_ohlcv("SH", "600519", 300)
    b = _synth_ohlcv("SH", "600519", 300)
    pd.testing.assert_frame_equal(a, b)
    assert list(a.columns) == ["datetime", "open", "high", "low", "close", "vol", "amount"]


def test_synth_ohlcv_differs_across_symbols() -> None:
    """不同标的应有不同行情（避免看板五指数全长得一样）。"""
    a = _synth_ohlcv("SH", "000001", 100)["close"].iloc[-1]
    b = _synth_ohlcv("SZ", "000001", 100)["close"].iloc[-1]
    assert a != b


def test_page_bars_newest_first_page() -> None:
    """分页语义与真实 /bars 一致：start=0 取最新 count 根，页内升序。"""
    df = _synth_ohlcv("SH", "600519", 1000)
    page0 = _page_bars(df, 0, 800)
    assert len(page0) == 800
    assert page0["datetime"].iloc[-1] == df["datetime"].iloc[-1]  # 最新一根在页尾
    assert page0["datetime"].is_monotonic_increasing

    page1 = _page_bars(df, 800, 800)
    assert len(page1) == 200
    assert page1["datetime"].iloc[-1] < page0["datetime"].iloc[0]  # 更早一段

    assert len(_page_bars(df, 5000, 800)) == 0  # 越界翻页返回空


# ── Mock 客户端契约 ──────────────────────────────────────────────────────────


async def test_mock_tdx_quotes_contract() -> None:
    """quotes df：market 列是 Market 枚举（QuoteStreamer._df_to_dicts 依赖）、
    字段覆盖 SSE 白名单（前端行情表 + 看板指数卡）。"""
    client = MockTdxClient()
    df = await client.get_security_quotes([(Market.SH, "000001"), (Market.SZ, "000001")])
    assert len(df) == 2
    # pandas 会把 IntEnum 列统一为 int64（真实客户端同样如此）；
    # QuoteStreamer._df_to_dicts 依赖 IntEnum 哈希相等完成 int → "SH" 映射
    assert df["market"].iloc[0] == Market.SH
    from easy_tdx.web.quote_streamer import _MARKET_NAMES

    assert _MARKET_NAMES.get(df["market"].iloc[0]) == "SH"
    for col in ("price", "pre_close", "open", "high", "low", "vol", "amount", "bid1", "ask_vol5"):
        assert col in df.columns
    # 指数与个股同名代码（SH000001 上证指数 / SZ000001 平安银行）行情不同
    assert df["price"].iloc[0] != df["price"].iloc[1]


async def test_mock_tdx_bars_daily_date_column() -> None:
    """日线返回 date 列（旧 /bars 契约），分页 start/count 生效。"""
    client = MockTdxClient()
    df = await client.get_security_bars(Market.SH, "600519", 4, 0, 50)  # 4 = DAY
    assert "date" in df.columns and "datetime" not in df.columns
    assert len(df) == 50
    assert df["date"].is_monotonic_increasing


async def test_mock_tdx_minute_and_stat() -> None:
    """分时 240 点 + 市场统计单行（看板两块数据源）。"""
    client = MockTdxClient()
    minute = await client.get_minute_time_data(Market.SH, "000001")
    assert len(minute) == 240
    assert {"datetime", "price", "vol"} <= set(minute.columns)

    stat = await client.get_market_stat()
    assert len(stat) == 1
    for col in ("up_count", "down_count", "total_count", "total_amount"):
        assert col in stat.columns


async def test_mock_mac_kline_contract() -> None:
    """MAC get_stock_kline：datetime 列 + float_shares（bars 路由规整依赖）。"""
    client = MockMacClient()
    df = await client.get_stock_kline(1, "600519", 4, 0, 30, 1, adjust=None)
    assert "datetime" in df.columns
    assert "float_shares" in df.columns
    assert len(df) == 30


async def test_mock_mac_quote_list_sort_and_columns() -> None:
    """排行行情：涨跌幅排序生效、列覆盖前端 RankRow 渲染需求。"""
    client = MockMacClient()
    desc = await client.get_stock_quotes_list(count=20, sort_order="DESC")
    asc = await client.get_stock_quotes_list(count=20, sort_order="ASC")
    assert len(desc) == 20
    for col in ("market", "code", "name", "close", "pre_close", "amount"):
        assert col in desc.columns
    d_pct = desc["close"] / desc["pre_close"]
    a_pct = asc["close"] / asc["pre_close"]
    assert d_pct.iloc[0] >= d_pct.iloc[-1]
    assert a_pct.iloc[0] <= a_pct.iloc[-1]


async def test_mock_mac_board_and_unusual() -> None:
    """板块列表/异动流：非空、字段齐（看板热度榜与异动雷达）。"""
    client = MockMacClient()
    boards = await client.get_board_list(count=500)
    assert len(boards) > 0
    assert {"code", "name", "price", "pre_close"} <= set(boards.columns)

    unusual = await client.get_unusual(market=1, count=60)
    assert 0 < len(unusual) <= 12
    assert {"time", "code", "name", "desc", "value"} <= set(unusual.columns)


async def test_mock_close_is_noop() -> None:
    """lifespan 关闭路径调用 close() 不抛异常。"""
    await MockTdxClient().close()
    await MockMacClient().close()


# ── TestClient 端到端（mock 模式 lifespan）───────────────────────────────────


def test_app_serves_synthetic_data_in_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """EASY_TDX_E2E_MOCK=1 时全应用 lifespan 用合成客户端，行情端点 200。"""
    from fastapi.testclient import TestClient

    from easy_tdx.web import create_app

    monkeypatch.setenv(E2E_MOCK_ENV, "1")
    app = create_app()
    with TestClient(app) as client:
        bars = client.get(
            "/api/v1/bars",
            params={"market": "SH", "code": "600519", "category": "DAY", "count": 30},
        )
        assert bars.status_code == 200
        assert len(bars.json()["data"]) == 30

        stat = client.get("/api/v1/market/stat")
        assert stat.status_code == 200
        assert stat.json()["data"][0]["up_count"] > 0

        rank = client.get("/api/v1/mac/quote-list", params={"count": 10})
        assert rank.status_code == 200
        assert len(rank.json()["data"]) == 10
