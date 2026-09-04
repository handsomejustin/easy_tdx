"""/board-mac/hotspot 热点滚动端点单测（离线，mock MAC 客户端）。

覆盖：后台构建状态机（building→ready / error 稳定 + retry 重建）、涨跌矩阵口径
（close 逐日环比）、每日排名与行集合并集（top/bottom 镜像）、行元数据
（days_in/streak/best_rank/复利 sum_pct/first_date）、今日列实时合并与
休市（全市场未移动）去重、当日缓存复用（不重拉日K）、无效 mode 400。
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

# ── 测试数据：21 个交易日（首根为窗口前锚点），三个板块涨跌幅恒定 ──────────────

_DATES = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-07-31", periods=21)]
# 轴 = 首根之后的 20 个交易日
_AXIS = _DATES[1:]


def _kline_df(start_close: float, daily: float) -> pd.DataFrame:
    closes = [start_close * (daily**i) for i in range(len(_DATES))]
    return pd.DataFrame({"datetime": pd.to_datetime(_DATES), "close": closes})


_BOARDS = [
    {"market": 1, "code": "881106", "name": "存储器", "price": 0.0, "pre_close": 0.0},
    {"market": 1, "code": "881105", "name": "CPO", "price": 0.0, "pre_close": 0.0},
    {"market": 1, "code": "881101", "name": "房地产开发", "price": 0.0, "pre_close": 0.0},
]


class _FakeHotspotMacClient:
    """按 code 返回恒定日涨跌幅 K 线的替身客户端。

    存储器 +5%/日、CPO +2%/日、房地产开发 -1%/日；实时报价由 live_prices
    提供（price/pre_close），缺省全部未移动（休市口径）。
    """

    def __init__(self, live_prices: dict[str, tuple[float, float]] | None = None):
        self.klines = {
            "881106": _kline_df(100.0, 1.05),
            "881105": _kline_df(200.0, 1.02),
            "881101": _kline_df(300.0, 0.99),
        }
        self.live_prices = live_prices or {}
        self.kline_calls = 0
        self.list_calls = 0

    async def get_board_list(self, board_type=None, count=5000, sort_column=None):
        self.list_calls += 1
        rows = []
        for b in _BOARDS:
            row = dict(b)
            price, pre = self.live_prices.get(b["code"], (0.0, 0.0))
            row["price"], row["pre_close"] = price, pre
            rows.append(row)
        return pd.DataFrame(rows)

    async def get_stock_kline(
        self, market=1, code="", period=None, start=0, count=800, times=1, adjust=None, **_
    ):
        self.kline_calls += 1
        return self.klines.get(code, pd.DataFrame())


def _hotspot_app(mac_client):
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
def _clean_cache(monkeypatch):
    from easy_tdx.web.routers import board_mac

    board_mac._hotspot_history_cache.clear()
    board_mac._hotspot_builds.clear()
    # 默认把"今天"钉在远期：不在 K 线轴内且实时报价未移动 → 不追加今日列
    monkeypatch.setattr(board_mac, "_today_str", lambda: "2030-01-01")
    yield
    board_mac._hotspot_history_cache.clear()
    board_mac._hotspot_builds.clear()


def _get(client, client_obj, **params):
    query = {"board_type": "HY", "days": 10, "per_day": 2, **params}
    resp = client.get("/api/v1/board-mac/hotspot", params=query)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"], client_obj


def _wait_ready(client, client_obj, timeout=10.0, **params):
    """轮询直至构建结束，返回最终 payload。"""
    deadline = time.time() + timeout
    data = None
    while time.time() < deadline:
        data, client_obj = _get(client, client_obj, **params)
        if data["status"] != "building":
            return data, client_obj
        time.sleep(0.02)
    raise AssertionError(f"热点矩阵构建超时: {data}")


def test_hotspot_build_matrix_and_metadata():
    """building→ready；矩阵口径、每日排名、行集合并集、行元数据全量校验。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeHotspotMacClient()
    with TestClient(_hotspot_app(fake)) as client:
        data, fake = _wait_ready(client, fake)

    assert data["status"] == "ready"
    assert data["dates"] == _AXIS[-10:]
    assert data["today_index"] is None  # 实时未移动 → 不追加今日列
    assert data["total_boards"] == 3

    rows = {r["code"]: r for r in data["rows"]}
    # 每日 +5%/+2% 恒定 → 前 2 名恒为存储器、CPO；房地产开发从不上榜
    assert set(rows) == {"881106", "881105"}

    mem = rows["881106"]
    assert mem["pct"] == [5.0] * 10
    assert mem["rank"] == [1] * 10
    assert mem["days_in"] == 10
    assert mem["streak"] == 10
    assert mem["best_rank"] == 1
    assert mem["first_date"] == _AXIS[-10]
    assert mem["sum_pct"] == pytest.approx(((1.05**10) - 1) * 100, abs=0.01)

    cpo = rows["881105"]
    assert cpo["rank"] == [2] * 10
    assert cpo["sum_pct"] == pytest.approx(((1.02**10) - 1) * 100, abs=0.01)


def test_hotspot_mode_bottom_mirrors_selection():
    """mode=bottom：每日最弱入选，排名语义镜像（1=跌幅最大）。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeHotspotMacClient()
    with TestClient(_hotspot_app(fake)) as client:
        data, _ = _wait_ready(client, fake, mode="bottom")

    rows = {r["code"]: r for r in data["rows"]}
    # 跌幅最深（-1%/日）与次深（+2%/日弱于 +5%）入选
    assert set(rows) == {"881101", "881105"}
    assert rows["881101"]["rank"] == [1] * 10
    assert rows["881101"]["days_in"] == 10
    assert rows["881101"]["sum_pct"] == pytest.approx(((0.99**10) - 1) * 100, abs=0.01)
    assert rows["881105"]["rank"] == [2] * 10


def test_hotspot_live_today_column_merged():
    """实时报价有移动 → 追加今日列：日期=今天、涨跌=price/pre_close、计入排名与连榜。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers import board_mac

    today = "2026-08-31"
    board_mac._today_str = lambda: today  # type: ignore[assignment]
    # 存储器 +3%、CPO 大跌 -3%（跌出当日前2）、地产 -0.5%（挤进当日前2）
    pre_a = 100.0 * (1.05**20)
    pre_b = 200.0 * (1.02**20)
    pre_c = 300.0 * (0.99**20)
    live = {
        "881106": (round(pre_a * 1.03, 4), round(pre_a, 4)),
        "881105": (round(pre_b * 0.97, 4), round(pre_b, 4)),
        "881101": (round(pre_c * 0.995, 4), round(pre_c, 4)),
    }
    fake = _FakeHotspotMacClient(live_prices=live)
    try:
        with TestClient(_hotspot_app(fake)) as client:
            data, _ = _wait_ready(client, fake)
    finally:
        board_mac._today_str = lambda: "2030-01-01"  # type: ignore[assignment]

    assert data["dates"][-1] == today
    assert data["today_index"] == len(data["dates"]) - 1
    assert len(data["dates"]) == 11

    rows = {r["code"]: r for r in data["rows"]}
    mem = rows["881106"]
    assert mem["pct"][-1] == 3.0
    assert mem["rank"][-1] == 1  # +3% 强于地产 -0.5% 与 CPO -3%
    assert mem["days_in"] == 11  # 窗口 10 日 + 今日列
    assert mem["streak"] == 11
    assert mem["sum_pct"] == pytest.approx(((1.05**10) * 1.03 - 1) * 100, abs=0.01)

    # CPO 今日大跌跌出前2 → 今日列计入排名但断连
    cpo = rows["881105"]
    assert cpo["pct"][-1] == -3.0
    assert cpo["rank"][-1] == 3
    assert cpo["days_in"] == 10
    assert cpo["streak"] == 0

    # 房地产开发仅今日上榜 → 进入行集合，首榜=今日
    estate = rows["881101"]
    assert estate["pct"][-1] == -0.5
    assert estate["rank"][-1] == 2
    assert estate["days_in"] == 1
    assert estate["first_date"] == today


def test_hotspot_market_idle_no_live_column():
    """全市场无一移动（盘前/休市）→ 不追加全 0 假列。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    # live_prices 为空 → 全部 price=pre_close=0 → any_moved=False
    fake = _FakeHotspotMacClient()
    with TestClient(_hotspot_app(fake)) as client:
        data, _ = _wait_ready(client, fake)
    assert data["today_index"] is None
    assert data["dates"] == _AXIS[-10:]
    assert data["session"] == "closed"


def test_hotspot_weekend_duplicate_live_suppressed():
    """周末隔夜 pre_close 未滚动：实时涨跌与历史末列重合 → 不追加重复的假今日列。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers import board_mac

    board_mac._today_str = lambda: "2026-08-29"  # type: ignore[assignment]  # 周六，不在轴内
    # price=最后一根 close、pre_close=前一根 close → 实时涨跌 == 历史末列（最后一个交易日的涨幅）
    live = {
        "881106": (100.0 * (1.05**20), 100.0 * (1.05**19)),
        "881105": (200.0 * (1.02**20), 200.0 * (1.02**19)),
        "881101": (300.0 * (0.99**20), 300.0 * (0.99**19)),
    }
    fake = _FakeHotspotMacClient(live_prices=live)
    try:
        with TestClient(_hotspot_app(fake)) as client:
            data, _ = _wait_ready(client, fake)
    finally:
        board_mac._today_str = lambda: "2030-01-01"  # type: ignore[assignment]

    assert data["today_index"] is None
    assert data["dates"] == _AXIS[-10:]  # 仍是 10 列窗口，无 08-29 重复列


def test_hotspot_history_cache_reused():
    """当日缓存复用：二次请求不重拉日K，仅刷新实时列表。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeHotspotMacClient()
    with TestClient(_hotspot_app(fake)) as client:
        _wait_ready(client, fake)
        kline_calls_after_build = fake.kline_calls
        list_calls_after_build = fake.list_calls
        data, _ = _get(client, fake)
    assert data["status"] == "ready"
    assert fake.kline_calls == kline_calls_after_build  # 日K零重复拉取
    assert fake.list_calls == list_calls_after_build + 1  # 实时列每次现取


def test_hotspot_error_stable_until_retry():
    """全部板块日K失败 → error 状态稳定（轮询不冲掉错误），retry=1 触发重建。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    class _EmptyKlineClient(_FakeHotspotMacClient):
        async def get_stock_kline(self, **_):  # noqa: D102 — 全部返回空
            self.kline_calls += 1
            return pd.DataFrame()

    fake = _EmptyKlineClient()
    with TestClient(_hotspot_app(fake)) as client:
        data, _ = _wait_ready(client, fake)
    assert data["status"] == "error"
    assert "日K" in data["error"]

    # 不带 retry 的再次请求：错误稳定（不再重拉日K）
    fake2 = fake
    with TestClient(_hotspot_app(fake2)) as client:
        data, _ = _get(client, fake2)
    assert data["status"] == "error"

    # retry=1 → 重新构建（仍失败，但状态机走 building）
    with TestClient(_hotspot_app(fake2)) as client:
        resp = client.get(
            "/api/v1/board-mac/hotspot",
            params={"board_type": "HY", "days": 10, "per_day": 2, "retry": "true"},
        )
        assert resp.status_code == 200
        # 任务刚启动：building 或（极快完成后的）error 均合法
        assert resp.json()["data"]["status"] in ("building", "error")


def test_hotspot_invalid_mode_returns_400():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeHotspotMacClient()
    with TestClient(_hotspot_app(fake)) as client:
        resp = client.get(
            "/api/v1/board-mac/hotspot",
            params={"board_type": "HY", "mode": "sideways"},
        )
    assert resp.status_code == 400
    assert "mode" in resp.json()["detail"]


def test_hotspot_missing_kline_board_excluded():
    """个别板块无日K：不参与排名，其余板块矩阵不受影响。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeHotspotMacClient()
    del fake.klines["881101"]  # 房地产开发缺日K
    with TestClient(_hotspot_app(fake)) as client:
        data, _ = _wait_ready(client, fake)
    assert data["total_boards"] == 2
    assert all(r["code"] != "881101" for r in data["rows"])


def test_hotspot_correlation_matrix_ready():
    """缓存就绪：相关矩阵直接可算，完全同向的两板块相关系数 = 1。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers import board_mac

    board_mac._hotspot_history_cache["HY"] = (
        "2030-01-01",
        {
            "axis": ["2026-08-10", "2026-08-11", "2026-08-12"],
            "pct": {
                "881100": {"2026-08-10": 5.0, "2026-08-11": 3.0, "2026-08-12": 1.0},
                "881200": {"2026-08-10": 4.0, "2026-08-11": 2.0, "2026-08-12": 0.0},
            },
            "names": {"881100": "甲板块", "881200": "乙板块"},
        },
    )
    fake = _FakeHotspotMacClient()
    try:
        with TestClient(_hotspot_app(fake)) as client:
            resp = client.get(
                "/api/v1/board-mac/hotspot-correlation",
                params={"board_type": "HY", "days": 5, "per_day": 2},
            )
    finally:
        board_mac._hotspot_history_cache.clear()

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "ready"
    assert [b["code"] for b in data["boards"]] == ["881100", "881200"]
    assert data["matrix"][0][0] == 1.0
    assert data["matrix"][0][1] == pytest.approx(1.0, abs=0.01)  # 完全线性同向
    assert data["matrix"][1][0] == data["matrix"][0][1]


def test_hotspot_correlation_building_passthrough():
    """无缓存：与 hotspot 相同的 building 状态透传，前端轮询即可。"""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    fake = _FakeHotspotMacClient()
    with TestClient(_hotspot_app(fake)) as client:
        resp = client.get("/api/v1/board-mac/hotspot-correlation", params={"board_type": "HY"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["status"] in ("building", "error", "ready")  # 单机假客户端极快时可能已完成
    if body["status"] == "building":
        assert 0.0 <= body["progress"] <= 1.0
