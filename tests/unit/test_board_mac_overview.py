"""/board-mac/overview 聚合端点单测（离线，mock MAC 客户端）。

覆盖：多排序键归并、当日涨跌幅口径（price/pre_close-1）、缺失指标置 null、
TTL 缓存命中、无效指标 400、空列表。
"""

from __future__ import annotations

import pytest


def _board_df(rows: list[dict]) -> object:
    import pandas as pd

    return pd.DataFrame(rows)


def _board_row(
    code: str,
    name: str,
    price: float,
    pre_close: float,
    sort_value: float = 0.0,
    leader: tuple[str, str, float, float] | None = None,
) -> dict:
    leader = leader or ("600000", "领涨股", price * 1.05, price)
    return {
        "market": 1,
        "code": code,
        "name": name,
        "price": price,
        "sort_value": sort_value,
        "pre_close": pre_close,
        "symbol_market": 1,
        "symbol_code": leader[0],
        "symbol_name": leader[1],
        "symbol_price": leader[2],
        "symbol_pre_close": leader[3],
    }


class _FakeOverviewMacClient:
    """按 BoardSortColumn 名称返回预置 DataFrame 的替身客户端。"""

    def __init__(self, frames: dict[str, object]):
        import pandas as pd

        self._frames = frames
        self._empty = pd.DataFrame()
        self.calls: list[str] = []

    async def get_board_list(self, board_type=None, count=10000, sort_column=None):
        name = getattr(sort_column, "name", None) or "CHANGE_PCT"  # 与真客户端默认一致
        self.calls.append(name)
        return self._frames.get(name, self._empty)


def _overview_app(mac_client):
    from fastapi import FastAPI

    from easy_tdx.web.errors import register_exception_handlers
    from easy_tdx.web.routers import board_mac

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(board_mac.router, prefix="/api/v1")
    app.state.tdx_client = object()
    app.state.mac_client = mac_client
    return app


@pytest.fixture(autouse=True)
def _clean_cache():
    from easy_tdx.web.routers import board_mac

    board_mac._overview_cache.clear()
    yield
    board_mac._overview_cache.clear()


def _get_overview(client, board_type="HY", metrics="SPEED,CHANGE_20D"):
    return client.get(
        "/api/v1/board-mac/overview",
        params={"board_type": board_type, "metrics": metrics},
    )


def test_overview_merge_and_change_pct():
    """基表 + 各排序键归并；涨跌幅按 price/pre_close-1 计算。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    frames = {
        "CHANGE_PCT": _board_df(
            [
                _board_row(
                    "881106", "种植业", 1039.93, 1031.20, leader=("600100", "A股票", 11.0, 10.0)
                ),
                _board_row(
                    "881101", "煤炭开采", 2200.0, 2244.0, leader=("600200", "B股票", 9.5, 10.0)
                ),
            ]
        ),
        "SPEED": _board_df(
            [
                _board_row("881106", "种植业", 1039.93, 1031.20, sort_value=0.52),
                _board_row("881101", "煤炭开采", 2200.0, 2244.0, sort_value=-0.11),
            ]
        ),
        "CHANGE_20D": _board_df(
            [
                _board_row("881106", "种植业", 1039.93, 1031.20, sort_value=6.3),
                _board_row("881101", "煤炭开采", 2200.0, 2244.0, sort_value=-2.4),
            ]
        ),
    }
    fake = _FakeOverviewMacClient(frames)
    with TestClient(_overview_app(fake)) as client:
        resp = _get_overview(client)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["board_type"] == "HY"
    assert data["count"] == 2

    rows = {r["code"]: r for r in data["rows"]}
    hy = rows["881106"]
    # 1039.93/1031.20-1 = +0.8465%
    assert hy["change_pct"] == pytest.approx(0.846, abs=0.01)
    assert hy["speed"] == 0.52
    assert hy["chg_20d"] == 6.3
    assert hy["chg_5d"] is None  # 未请求的指标置 null
    assert hy["leader_name"] == "A股票"
    assert hy["leader_change_pct"] == pytest.approx(10.0, abs=0.01)

    mt = rows["881101"]
    assert mt["change_pct"] == pytest.approx(-1.961, abs=0.01)
    assert mt["leader_change_pct"] == pytest.approx(-5.0, abs=0.01)

    # 基表(涨跌幅排序) + SPEED + CHANGE_20D 共 3 次调用
    assert sorted(fake.calls) == ["CHANGE_20D", "CHANGE_PCT", "SPEED"]


def test_overview_cache_hit_within_ttl():
    """TTL 内命中缓存，不再触发 MAC 调用；时间推进后重新拉取。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers import board_mac

    fake = _FakeOverviewMacClient(
        {"CHANGE_PCT": _board_df([_board_row("881001", "软件服务", 5000.0, 4900.0)])}
    )
    clock = {"t": 100.0}
    board_mac._now = lambda: clock["t"]  # type: ignore[assignment]
    try:
        with TestClient(_overview_app(fake)) as client:
            _get_overview(client)
            _get_overview(client)
        assert fake.calls.count("CHANGE_PCT") == 1

        clock["t"] += board_mac._OVERVIEW_TTL + 1
        with TestClient(_overview_app(fake)) as client:
            _get_overview(client)
        assert fake.calls.count("CHANGE_PCT") == 2
    finally:
        board_mac._now = board_mac.time.monotonic  # type: ignore[assignment]


def test_overview_cache_key_separates_board_type():
    """不同 board_type 的缓存相互独立。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    frames = {
        "CHANGE_PCT": _board_df([_board_row("881001", "软件服务", 5000.0, 4900.0)]),
        "GN": None,
    }
    fake = _FakeOverviewMacClient(frames)
    with TestClient(_overview_app(fake)) as client:
        _get_overview(client, board_type="HY")
        _get_overview(client, board_type="GN")
    assert fake.calls.count("CHANGE_PCT") == 2


def test_overview_invalid_metric_returns_400():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeOverviewMacClient({})
    with TestClient(_overview_app(fake)) as client:
        resp = _get_overview(client, metrics="SPEED,NOT_A_METRIC")
    assert resp.status_code == 400
    assert "NOT_A_METRIC" in resp.json()["detail"]


def test_overview_empty_base_list():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeOverviewMacClient({})
    with TestClient(_overview_app(fake)) as client:
        resp = _get_overview(client)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 0
    assert data["rows"] == []


def test_overview_zero_pre_close_change_pct_null():
    """pre_close 为 0（无行情）时涨跌幅为 null 而非异常/除零。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    frames = {"CHANGE_PCT": _board_df([_board_row("881999", "空数据板块", 0.0, 0.0)])}
    fake = _FakeOverviewMacClient(frames)
    with TestClient(_overview_app(fake)) as client:
        resp = _get_overview(client)
    assert resp.status_code == 200
    row = resp.json()["data"]["rows"][0]
    assert row["change_pct"] is None
    assert row["leader_change_pct"] is None
