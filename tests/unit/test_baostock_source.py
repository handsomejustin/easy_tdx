"""baostock 自动兜底数据源单测（离线，注入假 baostock 模块）。

覆盖：参数映射（代码/周期/复权）、offset 切片语义、停牌日剔除、
可用性门控（环境变量 / 未安装）、/bars 与 /bars/index 的端到端兜底、
TDX 正常时绝不触发兜底。
"""

from __future__ import annotations

import sys
import types

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# 假 baostock 模块
# ---------------------------------------------------------------------------


class _FakeLoginResult:
    error_code = "0"
    error_msg = ""


class _FakeResultData:
    def __init__(self, rows: list[list[str]]):
        self._rows = rows
        self._i = 0
        self.error_code = "0"
        self.error_msg = ""

    def next(self) -> bool:
        if self._i < len(self._rows):
            self._i += 1
            return True
        return False

    def get_row_data(self) -> list[str]:
        return self._rows[self._i - 1]


def _fake_rows(n: int, end: str = "2026-09-04") -> list[list[str]]:
    """n 个交易日的日线行：date, open, high, low, close, volume, amount, tradestatus。"""
    dates = pd.bdate_range(end=end, periods=n).strftime("%Y-%m-%d")
    return [[d, "10.0", "11.0", "9.5", "10.5", "100000", "1050000.0", "1"] for d in dates]


def _install_fake_bs(
    rows: list[list[str]] | None,
    captured: dict,
    *,
    query_error: bool = False,
) -> types.ModuleType:
    mod = types.ModuleType("baostock")

    def _login():  # type: ignore[no-untyped-def]
        captured["login"] = captured.get("login", 0) + 1
        return _FakeLoginResult()

    mod.login = _login  # type: ignore[attr-defined]
    mod.logout = lambda: None  # type: ignore[attr-defined]

    def query_history_k_data_plus(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        captured["calls"] = captured.get("calls", 0) + 1
        if query_error:
            result = _FakeResultData([])
            result.error_code = "10001"
            result.error_msg = "网络异常"
            return result
        return _FakeResultData(rows or [])

    mod.query_history_k_data_plus = query_history_k_data_plus  # type: ignore[attr-defined]
    sys.modules["baostock"] = mod
    return mod


@pytest.fixture()
def fake_bs(monkeypatch: pytest.MonkeyPatch):
    """注入假模块 + 复位模块级登录态；测试结束移除。"""
    from easy_tdx.sources import baostock as bs_source

    captured: dict = {}
    monkeypatch.setattr(bs_source, "_logged_in", False)
    monkeypatch.delenv(bs_source.BAOSTOCK_DISABLE_ENV, raising=False)
    _install_fake_bs(_fake_rows(10), captured)
    yield captured
    sys.modules.pop("baostock", None)


# ---------------------------------------------------------------------------
# 源模块行为
# ---------------------------------------------------------------------------


def test_fetch_maps_args_and_matches_contract(fake_bs):
    """代码/周期/复权映射正确；输出列序与 vol 单位（股，不换算）符合 /bars 契约。"""
    from easy_tdx.sources import baostock as bs_source

    df = bs_source.fetch_bars("SH", "600519", "DAY", 0, 5, "QFQ")
    assert df is not None and len(df) == 5
    assert list(df.columns) == ["date", "open", "close", "high", "low", "vol", "amount"]
    assert fake_bs["code"] == "sh.600519"
    assert fake_bs["frequency"] == "d"
    assert fake_bs["adjustflag"] == "2"  # QFQ
    # 时间升序，最后一根是最新交易日
    assert df["date"].iloc[-1] == pd.Timestamp("2026-09-04")
    assert (df["vol"] == 100000).all()  # baostock volume=股，与 /bars 契约一致，不换算


def test_offset_slice_matches_tdx_semantics(fake_bs):
    """start=跳过最新 N 根：30 根里 start=5, count=10 → 返回第 16~25 根。"""
    from easy_tdx.sources import baostock as bs_source

    _install_fake_bs(_fake_rows(30), fake_bs)
    df = bs_source.fetch_bars("SZ", "000001", "DAY", 5, 10, "QFQ")
    assert df is not None and len(df) == 10
    dates = df["date"].dt.strftime("%Y-%m-%d").tolist()
    expected = pd.bdate_range(end="2026-09-04", periods=30).strftime("%Y-%m-%d").tolist()
    assert dates[0] == expected[15]
    assert dates[-1] == expected[24]


def test_suspension_rows_dropped(fake_bs):
    """停牌日（tradestatus=0 / volume=0）剔除，对齐通达信 K 线口径。"""
    rows = _fake_rows(6)
    rows[2] = [rows[2][0], "0", "0", "0", "0", "0", "0", "0"]  # 停牌日
    _install_fake_bs(rows, fake_bs)
    from easy_tdx.sources import baostock as bs_source

    df = bs_source.fetch_bars("SZ", "000001", "DAY", 0, 10, "QFQ")
    assert df is not None and len(df) == 5
    assert (df["vol"] > 0).all()


def test_disabled_via_env(fake_bs, monkeypatch: pytest.MonkeyPatch):
    """EASY_TDX_BAOSTOCK=0 显式关闭：不安装也不调用。"""
    from easy_tdx.sources import baostock as bs_source

    monkeypatch.setenv(bs_source.BAOSTOCK_DISABLE_ENV, "0")
    assert bs_source.is_enabled() is False
    assert bs_source.fetch_bars("SH", "600519", "DAY", 0, 5, "QFQ") is None
    assert "login" not in fake_bs


def test_missing_module_returns_none(monkeypatch: pytest.MonkeyPatch):
    """未安装 baostock：静默返回 None（兜底环自动关闭）。"""
    monkeypatch.delenv("EASY_TDX_BAOSTOCK", raising=False)
    monkeypatch.setitem(sys.modules, "baostock", None)  # import 时抛 ImportError
    from easy_tdx.sources import baostock as bs_source

    assert bs_source.is_enabled() is False
    assert bs_source.fetch_bars("SH", "600519", "DAY", 0, 5, "QFQ") is None


def test_unsupported_inputs(fake_bs):
    """BJ 市场 / 分钟线周期 / 非法复权 / 超大窗口：不适用即 None。"""
    from easy_tdx.sources import baostock as bs_source

    assert bs_source.fetch_bars("BJ", "430047", "DAY", 0, 5, "QFQ") is None
    assert bs_source.fetch_bars("SH", "600519", "MIN_5", 0, 5, "QFQ") is None
    assert bs_source.fetch_bars("SH", "600519", "SEASON", 0, 5, "QFQ") is None
    assert bs_source.fetch_bars("SH", "600519", "DAY", 0, 5, "FOO") is None
    assert bs_source.fetch_bars("SH", "600519", "DAY", 99999, 800, "QFQ") is None
    assert "calls" not in fake_bs


def test_query_error_returns_none(fake_bs):
    """baostock 查询失败：返回 None 且不向上抛（兜底失败不改变原错误路径）。"""
    _install_fake_bs([], fake_bs, query_error=True)
    from easy_tdx.sources import baostock as bs_source

    assert bs_source.fetch_bars("SH", "600519", "DAY", 0, 5, "QFQ") is None


# ---------------------------------------------------------------------------
# /bars 与 /bars/index 端到端兜底
# ---------------------------------------------------------------------------


def _bars_app(mac_client, tdx_client):
    from fastapi import FastAPI

    from easy_tdx.web.errors import register_exception_handlers
    from easy_tdx.web.routers import bars

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(bars.router, prefix="/api/v1")
    app.state.tdx_client = tdx_client
    app.state.mac_client = mac_client
    return app


class _RaisingMac:
    async def get_stock_kline(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("MAC 连接失败")


class _RaisingTdx:
    async def get_security_bars(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("标准协议连接失败")

    async def get_index_bars(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("标准协议连接失败")


class _OkMac:
    async def get_stock_kline(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return pd.DataFrame(
            {
                "datetime": pd.bdate_range(end="2026-09-04", periods=5),
                "open": [10.0] * 5,
                "close": [10.5] * 5,
                "high": [11.0] * 5,
                "low": [9.5] * 5,
                "vol": [100000] * 5,
                "amount": [1050000.0] * 5,
                "float_shares": [0.0] * 5,
            }
        )


def test_bars_endpoint_falls_back_to_baostock(fake_bs, monkeypatch: pytest.MonkeyPatch):
    """MAC 与标准协议都失败 → baostock 兜底命中，响应带 source 字段。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _install_fake_bs(_fake_rows(10), fake_bs)
    with TestClient(_bars_app(_RaisingMac(), _RaisingTdx())) as client:
        resp = client.get("/api/v1/bars", params={"market": "SH", "code": "600519"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "baostock"
    assert body["count"] == 10
    assert "date" in body["data"][0]
    assert "change_pct" in body["data"][0]


def test_bars_endpoint_tdx_ok_never_calls_baostock(fake_bs):
    """TDX 正常出数时兜底绝不触发：source 为 None，baostock 零调用。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    with TestClient(_bars_app(_OkMac(), _RaisingTdx())) as client:
        resp = client.get("/api/v1/bars", params={"market": "SH", "code": "600519"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] is None
    assert body["count"] == 5
    assert "login" not in fake_bs


def test_bars_endpoint_no_fallback_available_keeps_error(fake_bs, monkeypatch: pytest.MonkeyPatch):
    """TDX 全败且兜底不可用：维持原错误语义（500），不返回空数据伪装成功。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.delenv("EASY_TDX_BAOSTOCK", raising=False)
    monkeypatch.setitem(sys.modules, "baostock", None)
    # raise_server_exceptions=False：模拟生产环境由服务端中间件返回 500
    with TestClient(
        _bars_app(_RaisingMac(), _RaisingTdx()), raise_server_exceptions=False
    ) as client:
        resp = client.get("/api/v1/bars", params={"market": "SH", "code": "600519"})
    assert resp.status_code == 500
    assert "连接失败" in resp.json()["detail"]


def test_index_endpoint_falls_back_to_baostock(fake_bs):
    """/bars/index：TDX 失败 → baostock 兜底（指数代码同格式）。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    _install_fake_bs(_fake_rows(10), fake_bs)
    with TestClient(_bars_app(None, _RaisingTdx())) as client:
        resp = client.get(
            "/api/v1/bars/index", params={"market": "SH", "code": "000001", "category": "DAY"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "baostock"
    assert fake_bs["code"] == "sh.000001"


# ---------------------------------------------------------------------------
# Warehouse 适配（BaostockClient / AutoKlineClient）
# ---------------------------------------------------------------------------


def test_baostock_client_maps_and_returns_datetime(fake_bs):
    """适配器满足 WarehouseSyncer 协议：market/period 数字与名称映射正确，
    输出 datetime 列（仓库 schema）。"""
    from easy_tdx.sources.baostock import BaostockClient

    df = BaostockClient().get_stock_kline(
        1, "600519", period="DAILY", start=0, count=5, adjust="QFQ"
    )
    assert len(df) == 5
    assert "datetime" in df.columns
    assert fake_bs["code"] == "sh.600519"
    assert fake_bs["frequency"] == "d"


def test_baostock_client_unsupported_market_returns_empty(fake_bs):
    """BJ（market=2）等不覆盖范围：返回空表（上层按无数据跳过），不报错。"""
    from easy_tdx.sources.baostock import BaostockClient

    df = BaostockClient().get_stock_kline(2, "430047", period="DAILY")
    assert len(df) == 0
    assert "calls" not in fake_bs


def test_baostock_client_no_data_returns_empty_not_raise(fake_bs):
    """无数据（如超出上市范围）返回空表而非异常。"""
    from easy_tdx.sources.baostock import BaostockClient

    _install_fake_bs([], fake_bs)
    df = BaostockClient().get_stock_kline(0, "000001", period="DAILY")
    assert len(df) == 0


def test_baostock_client_not_installed_raises_with_hint(monkeypatch: pytest.MonkeyPatch):
    """显式 --source baostock 但未安装：报错且信息带安装提示。"""
    monkeypatch.delenv("EASY_TDX_BAOSTOCK", raising=False)
    monkeypatch.setitem(sys.modules, "baostock", None)
    from easy_tdx.sources.baostock import BaostockClient

    with pytest.raises(RuntimeError, match="easy-tdx\[baostock\]"):
        BaostockClient().get_stock_kline(1, "600519", period="DAILY")


class _OkClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_stock_kline(self, market, code, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        return pd.DataFrame({"datetime": [1], "close": [10.0]})


class _EmptyThenOkClient(_OkClient):
    def get_stock_kline(self, market, code, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        return pd.DataFrame()


class _RaisingClient(_OkClient):
    def get_stock_kline(self, market, code, **kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        raise RuntimeError("主源失败")


def test_auto_kline_client_primary_ok_skips_fallback():
    from easy_tdx.sources import AutoKlineClient

    primary, fallback = _OkClient(), _OkClient()
    df = AutoKlineClient(primary, fallback).get_stock_kline(1, "600519", period="DAILY")
    assert len(df) == 1
    assert primary.calls == 1
    assert fallback.calls == 0


def test_auto_kline_client_primary_empty_falls_back():
    from easy_tdx.sources import AutoKlineClient

    primary, fallback = _EmptyThenOkClient(), _OkClient()
    df = AutoKlineClient(primary, fallback).get_stock_kline(1, "600519", period="DAILY")
    assert len(df) == 1
    assert fallback.calls == 1


def test_auto_kline_client_primary_error_falls_back():
    from easy_tdx.sources import AutoKlineClient

    fallback = _OkClient()
    df = AutoKlineClient(_RaisingClient(), fallback).get_stock_kline(1, "600519")
    assert len(df) == 1
    assert fallback.calls == 1


def test_auto_kline_client_fallback_error_propagates():
    from easy_tdx.sources import AutoKlineClient

    with pytest.raises(RuntimeError, match="主源失败"):
        AutoKlineClient(_RaisingClient(), _RaisingClient()).get_stock_kline(1, "600519")
