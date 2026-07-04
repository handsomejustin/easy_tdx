"""策略库（已保存策略）持久化 + Web API 测试（离线，无网络）。

覆盖：
- ``StrategyStore``：加入 / 列出 / 查看 / 删除 / 时间戳自动填充 / 重复 id
- 路由端到端：POST 创建、GET 列表、GET 详情、DELETE、404 路径、校验
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from easy_tdx.web.strategy_store import SavedStrategy, StrategyStore  # noqa: E402

# ── StrategyStore 单元测试 ────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path) -> StrategyStore:
    """每个测试独立 SQLite 文件，互不污染。"""
    return StrategyStore(db_path=tmp_path / "test_strategies.db")


def _sample_single(name: str = "双均线·平安") -> SavedStrategy:
    return SavedStrategy(
        id="",
        name=name,
        kind="single",
        strategy="ma_cross",
        strategy_label="双均线交叉",
        params={"fast": 5, "slow": 20},
        context={
            "symbol": "SZ:000001",
            "category": "DAY",
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
        },
        trade_config={"cash": 1_000_000, "commission": 0.0003, "execution": "next_open"},
        snapshot={"total_return": 0.352, "max_drawdown": -0.12, "sharpe": 1.42},
        tags=["银行", "长线"],
        notes="回撤可控",
    )


def _sample_portfolio(name: str = "组合·消费双雄") -> SavedStrategy:
    return SavedStrategy(
        id="",
        name=name,
        kind="portfolio",
        strategy="rsi_reversal",
        strategy_label="RSI 反转",
        params={"period": 14, "oversold": 30},
        context={"stocks": ["SH:600519", "SZ:000858"]},
        snapshot={"total_return": 0.18},
    )


def test_add_assigns_id_and_timestamps(store: StrategyStore):
    rec = store.add(_sample_single())
    assert rec.id and len(rec.id) == 12
    assert rec.created_at
    assert rec.updated_at == rec.created_at


def test_list_round_trip_preserves_all_fields(store: StrategyStore):
    original = store.add(_sample_single())
    items = store.list_all()
    assert len(items) == 1
    got = items[0]
    assert got.id == original.id
    assert got.name == "双均线·平安"
    assert got.kind == "single"
    assert got.params == {"fast": 5, "slow": 20}
    assert got.context["symbol"] == "SZ:000001"
    assert got.trade_config["cash"] == 1_000_000
    assert got.snapshot["total_return"] == pytest.approx(0.352)
    assert got.tags == ["银行", "长线"]
    assert got.notes == "回撤可控"


def test_list_orders_by_created_desc(store: StrategyStore):
    a = store.add(_sample_single(name="first"))
    b = store.add(_sample_portfolio(name="second"))
    names = [x.name for x in store.list_all()]
    # 后加的在前
    assert names == ["second", "first"]
    assert {x.id for x in (a, b)} == {a.id, b.id}


def test_get_returns_none_for_missing(store: StrategyStore):
    assert store.get("nope") is None


def test_get_returns_record(store: StrategyStore):
    rec = store.add(_sample_portfolio())
    got = store.get(rec.id)
    assert got is not None
    assert got.kind == "portfolio"
    assert got.context["stocks"] == ["SH:600519", "SZ:000858"]


def test_delete_removes_record(store: StrategyStore):
    rec = store.add(_sample_single())
    assert store.delete(rec.id) is True
    assert store.get(rec.id) is None
    assert store.list_all() == []


def test_delete_missing_returns_false(store: StrategyStore):
    assert store.delete("nonexistent") is False


def test_store_creates_db_file_and_schema(tmp_path):
    db_path = tmp_path / "nested" / "strategies.db"
    s = StrategyStore(db_path=db_path)
    assert db_path.exists()
    # schema 已建表 + 索引
    with sqlite3.connect(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "strategies" in tables
    assert {"idx_strategies_kind", "idx_strategies_strategy", "idx_strategies_created"} <= indexes
    # 可正常写入
    s.add(_sample_single())
    assert len(s.list_all()) == 1


def test_json_fields_with_unicode(store: StrategyStore):
    """中文标签/备注应无损往返（ensure_ascii=False 落库）。"""
    rec = store.add(
        SavedStrategy(
            id="",
            name="测试·中文🎉",
            kind="single",
            strategy="macd",
            notes="这是一段中文备注",
            tags=["标签一", "标签二"],
        )
    )
    got = store.get(rec.id)
    assert got is not None
    assert got.name == "测试·中文🎉"
    assert got.notes == "这是一段中文备注"
    assert got.tags == ["标签一", "标签二"]


# ── 路由端到端测试（TestClient）──────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch) -> TestClient:
    """构造一个用临时 SQLite 文件的独立 app + store 单例。"""
    # 用 monkeypatch 替换 get_store 返回的路径，保证测试隔离
    from easy_tdx.web import strategy_store as mod

    test_store = StrategyStore(db_path=tmp_path / "router_strategies.db")
    # 替换单例，避免污染全局
    monkeypatch.setattr(mod, "_store", test_store)

    from easy_tdx.web.routers.strategies import router as strategies_router

    app = FastAPI()
    app.include_router(strategies_router, prefix="/api/v1")
    # 复用项目的 ValueError → 400 处理
    from easy_tdx.web.errors import register_exception_handlers

    register_exception_handlers(app)
    return TestClient(app)


def _create_payload(kind: str = "single", **over) -> dict:
    base = {
        "name": "我的策略",
        "kind": kind,
        "strategy": "ma_cross",
        "strategy_label": "双均线交叉",
        "params": {"fast": 5, "slow": 20},
        "context": {"symbol": "SZ:000001"},
        "trade_config": {"cash": 1000000},
        "snapshot": {"total_return": 0.35, "sharpe": 1.4},
        "tags": ["银行"],
        "notes": "观察中",
    }
    base.update(over)
    return base


def test_router_create_then_list_get_delete(client: TestClient):
    # 1. 创建
    resp = client.post("/api/v1/strategies", json=_create_payload())
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"]
    assert created["name"] == "我的策略"
    assert created["params"] == {"fast": 5, "slow": 20}
    assert created["created_at"]
    sid = created["id"]

    # 2. 列表
    resp = client.get("/api/v1/strategies")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["strategies"][0]["id"] == sid

    # 3. 详情
    resp = client.get(f"/api/v1/strategies/{sid}")
    assert resp.status_code == 200
    assert resp.json()["snapshot"]["total_return"] == pytest.approx(0.35)

    # 4. 删除
    resp = client.delete(f"/api/v1/strategies/{sid}")
    assert resp.status_code == 204

    # 5. 列表为空
    assert client.get("/api/v1/strategies").json()["count"] == 0


def test_router_get_missing_returns_400(client: TestClient):
    # 不存在的 id → ValueError → 400（项目错误处理约定）
    resp = client.get("/api/v1/strategies/nonexistent")
    assert resp.status_code == 400


def test_router_delete_missing_returns_400(client: TestClient):
    resp = client.delete("/api/v1/strategies/nonexistent")
    assert resp.status_code == 400


def test_router_rejects_empty_name(client: TestClient):
    resp = client.post("/api/v1/strategies", json=_create_payload(name=""))
    assert resp.status_code == 422  # Pydantic 校验失败


def test_router_rejects_invalid_kind(client: TestClient):
    resp = client.post("/api/v1/strategies", json=_create_payload(kind="bogus"))
    assert resp.status_code == 422


def test_router_accepts_portfolio_kind(client: TestClient):
    payload = _create_payload(
        kind="portfolio",
        strategy="rsi_reversal",
        context={"stocks": ["SH:600519", "SZ:000858"]},
    )
    resp = client.post("/api/v1/strategies", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "portfolio"
    assert body["context"]["stocks"] == ["SH:600519", "SZ:000858"]
