"""Web API tests (offline, no network).

Covers: schemas, error handling, app factory, DI, all routers,
        CLI serve command, OpenAPI schema generation.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Task 2: Schemas & Error Handling
# ---------------------------------------------------------------------------


def test_market_enum_values():
    """MarketEnum should map string names to int values matching Market enum."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.schemas import MarketEnum

    assert MarketEnum.SZ == 0
    assert MarketEnum.SH == 1
    assert MarketEnum.BJ == 2


def test_kline_category_enum():
    """KlineCategoryEnum should map string names to int values."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.schemas import KlineCategoryEnum

    assert KlineCategoryEnum.MIN_5 == 0
    assert KlineCategoryEnum.DAY == 4
    assert KlineCategoryEnum.WEEK == 5


def test_quote_request_validation():
    """QuoteRequest should validate stocks list."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.schemas import QuoteRequest

    req = QuoteRequest(stocks=[{"market": "SZ", "code": "000001"}])
    assert len(req.stocks) == 1
    assert req.stocks[0].market == "SZ"
    assert req.stocks[0].code == "000001"


def test_chanlun_request_defaults():
    """ChanlunRequest should have sensible defaults."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.schemas import ChanlunRequest

    req = ChanlunRequest(market="SZ", code="000001")
    assert req.category == "DAY"
    assert req.count == 800


def test_api_error_response():
    """ApiErrorResponse should serialize correctly."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.errors import ApiErrorResponse

    err = ApiErrorResponse(error="test error", detail="some detail")
    d = err.model_dump()
    assert d["error"] == "test error"
    assert d["detail"] == "some detail"


# ---------------------------------------------------------------------------
# Task 3: App Factory & Dependency Injection
# ---------------------------------------------------------------------------


def test_create_app_returns_fastapi_instance():
    """create_app should return a FastAPI app with routers mounted."""
    pytest.importorskip("fastapi")
    from easy_tdx.web import create_app

    app = create_app()
    assert app.title == "easy-tdx API"

    # Check routers are mounted
    # FastAPI 0.141+ 的 app.routes 含 _IncludedRouter（无 path 属性），改用
    # OpenAPI schema 验证（WebSocket 不进 schema，由 test_full_app_routes_registered 覆盖）
    routes = list(app.openapi()["paths"].keys())
    assert any("/api/v1/security" in r for r in routes)
    assert any("/api/v1/bars" in r for r in routes)
    assert any("/api/v1/chanlun" in r for r in routes)
    assert any("/api/v1/watchlist" in r for r in routes)
    assert any("/api/v1/stream/quotes" in r for r in routes)


def test_deps_get_client_type():
    """get_client should be callable (actual client creation needs network)."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.deps import get_client

    assert callable(get_client)


# ---------------------------------------------------------------------------
# Task 4: Market Router
# ---------------------------------------------------------------------------


def test_market_router_endpoints():
    """Market router should define all expected endpoints."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.routers.market import router

    paths = [r.path for r in router.routes]
    assert "/security/count" in paths
    assert "/security/list" in paths
    assert "/security/list-all" in paths
    assert "/quotes" in paths
    assert "/market/stat" in paths
    assert "/fund-flow" in paths
    assert "/fund-flow/history" in paths


# ---------------------------------------------------------------------------
# Task 5: Bars Router
# ---------------------------------------------------------------------------


def test_bars_router_endpoints():
    """Bars router should define all expected endpoints."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.routers.bars import router

    paths = [r.path for r in router.routes]
    assert "/bars" in paths
    assert "/bars/index" in paths
    assert "/minute" in paths
    assert "/minute/history" in paths
    assert "/transaction" in paths
    assert "/transaction/history" in paths


# ---------------------------------------------------------------------------
# Task 6: Finance Router
# ---------------------------------------------------------------------------


def test_finance_router_endpoints():
    """Finance router should define all expected endpoints."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.routers.finance import router

    paths = [r.path for r in router.routes]
    assert "/xdxr" in paths
    assert "/finance" in paths
    assert "/company/category" in paths
    assert "/company/content" in paths
    assert "/financial/file-list" in paths
    assert "/financial/records" in paths


# ---------------------------------------------------------------------------
# Task 7: Block Router
# ---------------------------------------------------------------------------


def test_block_router_endpoints():
    """Block router should define expected endpoints."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.routers.block import router

    paths = [r.path for r in router.routes]
    assert "/block" in paths


# ---------------------------------------------------------------------------
# Task 8: Chanlun Router
# ---------------------------------------------------------------------------


def test_chanlun_router_endpoints():
    """Chanlun router should define the analyze endpoint."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.routers.chanlun import router

    paths = [r.path for r in router.routes]
    assert "/chanlun/analyze" in paths


# ---------------------------------------------------------------------------
# Task 9: Realtime Router
# ---------------------------------------------------------------------------


def test_realtime_router_endpoints():
    """Realtime router should define the WebSocket endpoint."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.routers.realtime import router

    paths = [r.path for r in router.routes]
    assert any("realtime" in p for p in paths)


# ---------------------------------------------------------------------------
# Task 10: CLI serve command
# ---------------------------------------------------------------------------


def test_serve_command_exists():
    """CLI should have a serve command registered."""
    pytest.importorskip("fastapi")
    from easy_tdx.cli import cli

    assert "serve" in cli.commands


# ---------------------------------------------------------------------------
# Task 11: Integration — route registration & OpenAPI
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regression: input validation (case-insensitive + invalid → ValueError → 400)
# ---------------------------------------------------------------------------


def test_convert_market_lowercase():
    """market_from_str should accept lowercase input."""
    pytest.importorskip("fastapi")
    from easy_tdx.models.enums import Market
    from easy_tdx.web.convert import market_from_str

    assert market_from_str("sz") == Market.SZ
    assert market_from_str("sh") == Market.SH
    assert market_from_str("Bj") == Market.BJ


def test_convert_market_invalid_raises_valueerror():
    """market_from_str should raise ValueError for invalid market codes."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.convert import market_from_str

    with pytest.raises(ValueError, match="无效市场代码"):
        market_from_str("ZZZ")


def test_convert_category_from_int_string():
    """category_from_str should accept numeric string like '4'."""
    pytest.importorskip("fastapi")
    from easy_tdx.models.enums import KlineCategory
    from easy_tdx.web.convert import category_from_str

    assert category_from_str("4") == KlineCategory.DAY


def test_convert_category_invalid_raises_valueerror():
    """category_from_str should raise ValueError for invalid period."""
    pytest.importorskip("fastapi")
    from easy_tdx.web.convert import category_from_str

    with pytest.raises(ValueError, match="无效K线周期"):
        category_from_str("INVALID_PERIOD")


# ---------------------------------------------------------------------------
# /bars 迁移到 MacClient：KlineCategory→(Period,times) 映射 + adjust 转换
# (Issue #43)
# ---------------------------------------------------------------------------


def test_period_times_from_category_mapping():
    """KlineCategory → (Period, times) 完整映射，重点 YEAR/SEASON 值不同。"""
    pytest.importorskip("fastapi")
    from easy_tdx.mac.enums import Period
    from easy_tdx.models.enums import KlineCategory
    from easy_tdx.web.convert import period_times_from_category

    expected = {
        KlineCategory.MIN_5: (Period.MIN_5, 1),
        KlineCategory.MIN_15: (Period.MIN_15, 1),
        KlineCategory.MIN_30: (Period.MIN_30, 1),
        KlineCategory.MIN_60: (Period.MIN_60, 1),
        KlineCategory.DAY: (Period.DAILY, 1),
        KlineCategory.WEEK: (Period.WEEKLY, 1),
        KlineCategory.MONTH: (Period.MONTHLY, 1),
        KlineCategory.MIN_1: (Period.MIN_1, 1),
        KlineCategory.YEAR: (Period.YEARLY, 1),  # 值 9 → Period.YEARLY 值 11
        KlineCategory.SEASON: (Period.QUARTERLY, 1),  # SEASON → QUARTERLY
    }
    for cat, want in expected.items():
        assert period_times_from_category(cat) == want, f"{cat} 应映射到 {want}"


def test_period_times_from_category_rejects_unmappable():
    """无法映射的 KlineCategory 值（如 MIN_3=8）应抛 ValueError。"""
    pytest.importorskip("fastapi")
    from easy_tdx.web.convert import period_times_from_category

    with pytest.raises(ValueError, match="无法映射"):
        period_times_from_category(8)  # MIN_3 不在 /bars 支持范围


def test_adjust_from_str_accepts_name_case_and_int():
    """adjust_from_str 支持 NONE/QFQ/HFQ 名称（大小写）和数字字符串。"""
    pytest.importorskip("fastapi")
    from easy_tdx.mac.enums import Adjust
    from easy_tdx.web.convert import adjust_from_str

    assert adjust_from_str("QFQ") == Adjust.QFQ
    assert adjust_from_str("qfq") == Adjust.QFQ
    assert adjust_from_str("1") == Adjust.QFQ  # 数字字符串
    assert adjust_from_str("NONE") == Adjust.NONE
    assert adjust_from_str("none") == Adjust.NONE
    assert adjust_from_str("0") == Adjust.NONE
    assert adjust_from_str("HFQ") == Adjust.HFQ
    assert adjust_from_str("2") == Adjust.HFQ


def test_adjust_from_str_invalid_raises():
    """非法复权类型应抛 ValueError。"""
    pytest.importorskip("fastapi")
    from easy_tdx.web.convert import adjust_from_str

    with pytest.raises(ValueError, match="无效复权类型"):
        adjust_from_str("XXX")


def test_normalize_mac_df_daily_plus():
    """日线规整：datetime→date（截断时分）、drop float_shares、OHLC 顺序 open/close/high/low。"""
    pytest.importorskip("fastapi")
    import pandas as pd

    from easy_tdx.web.routers.bars import _normalize_mac_df

    df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-07-10 15:00:00"), pd.Timestamp("2026-07-11 15:00:00")],
            "open": [10.0, 10.5],
            "high": [10.8, 10.9],
            "low": [9.9, 10.3],
            "close": [10.5, 10.6],
            "vol": [1000.0, 1100.0],
            "amount": [10500.0, 11600.0],
            "float_shares": [0.0, 0.0],
        }
    )
    out = _normalize_mac_df(df, daily_plus=True)
    # 时间列：datetime → date，且截断为 00:00:00
    assert "date" in out.columns
    assert "datetime" not in out.columns
    assert out["date"].iloc[0] == pd.Timestamp("2026-07-11 00:00:00") - pd.Timedelta(days=1)
    # drop float_shares
    assert "float_shares" not in out.columns
    # 列顺序：date 在前，OHLC 顺序 open/close/high/low
    assert list(out.columns) == ["date", "open", "close", "high", "low", "vol", "amount"]


def test_normalize_mac_df_intraday_keeps_datetime():
    """分钟线规整：保留 datetime 列（含时分）。"""
    pytest.importorskip("fastapi")
    import pandas as pd

    from easy_tdx.web.routers.bars import _normalize_mac_df

    df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-07-10 09:35:00")],
            "open": [10.0],
            "high": [10.8],
            "low": [9.9],
            "close": [10.5],
            "vol": [1000.0],
            "amount": [10500.0],
        }
    )
    out = _normalize_mac_df(df, daily_plus=False)
    assert "datetime" in out.columns
    assert "date" not in out.columns
    # 时分保留
    assert out["datetime"].iloc[0] == pd.Timestamp("2026-07-10 09:35:00")
    assert list(out.columns) == ["datetime", "open", "close", "high", "low", "vol", "amount"]


def test_normalize_mac_df_empty_noop():
    """空 DataFrame 规整不报错。"""
    pytest.importorskip("fastapi")
    import pandas as pd

    from easy_tdx.web.routers.bars import _normalize_mac_df

    out = _normalize_mac_df(pd.DataFrame(), daily_plus=True)
    assert out.empty


def test_is_daily_plus_covers_all_categories():
    """daily_plus 判定必须按显式周期表，不能按枚举整数大小（issue #49）。

    KlineCategory 值无序（MIN_1=7、MIN_3=8 > DAY=4），整数比较会把 1/3 分钟线
    误判成日线，导致 datetime 被截断为 00:00:00 且列名变 date。
    """
    pytest.importorskip("fastapi")
    from easy_tdx.models.enums import KlineCategory
    from easy_tdx.web.routers.bars import _is_daily_plus

    intraday = {
        KlineCategory.MIN_1,
        KlineCategory.MIN_3,
        KlineCategory.MIN_5,
        KlineCategory.MIN_15,
        KlineCategory.MIN_30,
        KlineCategory.MIN_60,
    }
    for cat in KlineCategory:
        assert _is_daily_plus(cat) == (cat not in intraday), f"{cat.name} 判定错误"


class _FakeMacClient:
    """替身 AsyncMacClient：固定返回 MacClient 风格的 K 线 DataFrame。"""

    def __init__(self, df):
        import pandas as pd

        self._df = df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
        self.calls: list[dict] = []

    async def get_stock_kline(self, market, code, period, start, count, times, **kwargs):
        self.calls.append({"period": period, "adjust": kwargs.get("adjust")})
        return self._df


def _bars_app(mac_client):
    """构造只挂 bars 路由的最小 app（无 lifespan，不触发真实行情连接）。"""
    from fastapi import FastAPI

    from easy_tdx.web.routers import bars

    app = FastAPI()
    app.include_router(bars.router, prefix="/api/v1")
    app.state.tdx_client = object()  # mac_client 非 None 时不会被用到
    app.state.mac_client = mac_client
    return app


def test_bars_min1_endpoint_keeps_datetime():
    """端到端回归（issue #49）：/bars MIN_1 必须返回 datetime 列且保留时分。"""
    pytest.importorskip("fastapi")
    import pandas as pd
    from fastapi.testclient import TestClient

    mac_df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-08-14 09:31:00"), pd.Timestamp("2026-08-14 09:32:00")],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "vol": [1000.0, 1100.0],
            "amount": [10100.0, 11220.0],
            "float_shares": [0.0, 0.0],
        }
    )
    fake = _FakeMacClient(mac_df)
    with TestClient(_bars_app(fake)) as client:
        resp = client.get(
            "/api/v1/bars",
            params={"market": "SH", "code": "603179", "category": "MIN_1", "count": 2},
        )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 2
    for row in rows:
        assert "datetime" in row and "date" not in row
    assert rows[0]["datetime"] == "2026-08-14T09:31:00"
    assert rows[1]["datetime"] == "2026-08-14T09:32:00"


def test_bars_day_endpoint_returns_date():
    """端到端对照：/bars DAY 仍返回 date 列（00:00:00），确认修复无回归。"""
    pytest.importorskip("fastapi")
    import pandas as pd
    from fastapi.testclient import TestClient

    mac_df = pd.DataFrame(
        {
            "datetime": [pd.Timestamp("2026-08-14 15:00:00")],
            "open": [10.0],
            "high": [10.2],
            "low": [9.9],
            "close": [10.1],
            "vol": [1000.0],
            "amount": [10100.0],
            "float_shares": [0.0],
        }
    )
    fake = _FakeMacClient(mac_df)
    with TestClient(_bars_app(fake)) as client:
        resp = client.get(
            "/api/v1/bars", params={"market": "SH", "code": "603179", "category": "DAY", "count": 1}
        )
    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert "date" in rows[0] and "datetime" not in rows[0]
    assert rows[0]["date"] == "2026-08-14T00:00:00"


def test_full_app_routes_registered():
    """All routers should be mounted and accessible."""
    pytest.importorskip("fastapi")
    from easy_tdx.web import create_app

    app = create_app()
    # FastAPI 0.141+ 的 include_router 是 _IncludedRouter 延迟对象，app.routes
    # 不再平铺子路由；用 OpenAPI schema 验证注册结果（面向行为而非内部结构）。
    # WebSocket 路由不进 OpenAPI，单独用 _IncludedRouter 展开验证。
    all_paths = list(app.openapi()["paths"].keys())
    expected_prefixes = [
        "/api/v1/security",
        "/api/v1/bars",
        "/api/v1/xdxr",
        "/api/v1/block",
        "/api/v1/chanlun",
        "/api/v1/announcements",
        "/api/v1/sina/financial-report",
        "/api/v1/watchlist",
        "/api/v1/stream/quotes",
    ]
    for prefix in expected_prefixes:
        matched = any(prefix in p for p in all_paths)
        assert matched, f"Expected route with prefix '{prefix}' not found in {all_paths}"

    # WebSocket 路由验证：经 _IncludedRouter.original_router 展开找 ws 路径
    ws_paths: list[str] = []

    def _collect(routes: list) -> None:
        for r in routes:
            path = getattr(r, "path", None)
            if path:
                ws_paths.append(path)
            orig = getattr(r, "original_router", None)
            if orig is not None:
                _collect(getattr(orig, "routes", []))

    _collect(app.routes)
    assert any("/ws/realtime" in p for p in ws_paths), f"WS route missing in {ws_paths}"


def test_openapi_schema_generated():
    """OpenAPI schema should be auto-generated and contain key paths."""
    pytest.importorskip("fastapi")
    from easy_tdx.web import create_app

    app = create_app()
    schema = app.openapi()
    assert schema["info"]["title"] == "easy-tdx API"
    assert "/api/v1/security/count" in schema["paths"]
    assert "/api/v1/bars" in schema["paths"]
    assert "/api/v1/chanlun/analyze" in schema["paths"]
    # WebSocket routes are NOT included in OpenAPI schema by default;
    # they are verified in test_full_app_routes_registered instead.
    # Just ensure REST paths are present.
    assert "/api/v1/fund-flow" in schema["paths"]
