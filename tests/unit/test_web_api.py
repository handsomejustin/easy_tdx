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
    routes = [r.path for r in app.routes]
    assert any("/api/v1/security" in r for r in routes)
    assert any("/api/v1/bars" in r for r in routes)
    assert any("/api/v1/chanlun" in r for r in routes)
    assert any("/ws/realtime" in r for r in routes)


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


def test_full_app_routes_registered():
    """All routers should be mounted and accessible."""
    pytest.importorskip("fastapi")
    from easy_tdx.web import create_app

    app = create_app()
    all_paths = [r.path for r in app.routes]
    expected_prefixes = [
        "/api/v1/security",
        "/api/v1/bars",
        "/api/v1/xdxr",
        "/api/v1/block",
        "/api/v1/chanlun",
        "/api/v1/announcements",
        "/api/v1/sina/financial-report",
        "/ws/realtime",
    ]
    for prefix in expected_prefixes:
        matched = any(prefix in p for p in all_paths)
        assert matched, f"Expected route with prefix '{prefix}' not found in {all_paths}"


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
