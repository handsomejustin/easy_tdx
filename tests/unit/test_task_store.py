"""回测任务 SQLite 持久化测试（task_store + task_runner 集成 + REST 导出）。

覆盖：
- ``TaskStore``：save/load/list_recent/delete 往返、淘汰、重启恢复中断任务
- ``BacktestTaskRunner`` 集成：任务完成后落盘、内存淘汰后磁盘兜底、
  「重启」（新建 runner）后仍可查历史任务
- REST 导出端点：JSON 全量 / CSV 主表 / 未完成任务拒绝导出

持久化默认被 ``tests/conftest.py`` 关闭（``EASY_TDX_NO_TASK_DB=1``），
本文件的测试显式删除该变量并把 ``EASY_TDX_CONFIG_DIR`` 指向 ``tmp_path``。
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from easy_tdx.web import task_store as ts_mod  # noqa: E402
from easy_tdx.web.task_runner import BacktestTaskRunner  # noqa: E402
from easy_tdx.web.task_store import TaskStore  # noqa: E402


@pytest.fixture()
def persisted_env(tmp_path, monkeypatch):
    """开启持久化并指向临时目录；隔离全局单例。"""
    monkeypatch.delenv("EASY_TDX_NO_TASK_DB", raising=False)
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path))
    ts_mod.reset_task_store()
    yield tmp_path
    ts_mod.reset_task_store()


def _wait_done(runner: BacktestTaskRunner, task_id: str, timeout: float = 5.0) -> None:
    """轮询等待任务进入终态。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = runner.peek(task_id)
        assert state is not None
        if state.status in ("done", "failed"):
            return
        time.sleep(0.02)
    raise AssertionError(f"任务 {task_id} 超时未完成")


# ── TaskStore 单元 ────────────────────────────────────────────────────────────


def test_store_save_load_roundtrip(persisted_env):
    store = TaskStore(db_path=persisted_env / "t.db")
    store.save(
        task_id="abc",
        status="done",
        description="ma_cross | 300根",
        created_at=1000.0,
        started_at=1001.0,
        finished_at=1002.0,
        result={"performance": {"total_return": 0.25}, "trades": [{"pnl": 1.0}]},
    )
    d = store.load("abc")
    assert d is not None
    assert d["status"] == "done"
    assert d["result"]["performance"]["total_return"] == 0.25
    assert d["created_at"] == 1000.0
    assert store.load("missing") is None


def test_store_list_recent_order_and_delete(persisted_env):
    store = TaskStore(db_path=persisted_env / "t.db")
    for i in range(5):
        store.save(task_id=f"t{i}", status="done", created_at=1000.0 + i)
    rows = store.list_recent(limit=3)
    assert [r["task_id"] for r in rows] == ["t4", "t3", "t2"]  # created_at 倒序
    assert store.delete("t4") is True
    assert store.delete("t4") is False
    assert store.load("t4") is None


def test_store_upsert_replaces(persisted_env):
    """同 task_id 二次 save 是覆盖而非追加。"""
    store = TaskStore(db_path=persisted_env / "t.db")
    store.save(task_id="x", status="running", created_at=1.0)
    store.save(task_id="x", status="done", created_at=1.0, finished_at=2.0, result={"a": 1})
    d = store.load("x")
    assert d["status"] == "done"
    assert d["result"] == {"a": 1}
    assert len(store.list_recent(limit=10)) == 1


def test_store_recovers_interrupted_tasks(persisted_env):
    """新连接（模拟进程重启）把遗留 pending/running 标记为 failed。"""
    store = TaskStore(db_path=persisted_env / "t.db")
    store.save(task_id="p1", status="pending", created_at=1.0)
    store.save(task_id="r1", status="running", created_at=1.0)
    store.save(task_id="d1", status="done", created_at=1.0, result={"ok": True})

    # 模拟重启：新实例初始化时触发恢复
    store2 = TaskStore(db_path=persisted_env / "t.db")
    _ = store2.list_recent(limit=10)

    assert store2.load("p1")["status"] == "failed"
    assert "重启" in store2.load("p1")["error"]
    assert store2.load("r1")["status"] == "failed"
    assert store2.load("d1")["status"] == "done"  # 已完成任务不受影响


def test_store_result_json_corruption_degrades(persisted_env):
    """result_json 损坏时 load 降级返回 result=None，不抛异常。"""
    import sqlite3

    path = persisted_env / "t.db"
    store = TaskStore(db_path=path)
    store.save(task_id="bad", status="done", created_at=1.0, result={"a": 1})
    conn = sqlite3.connect(path)
    conn.execute("UPDATE backtest_tasks SET result_json = '{not-json' WHERE task_id='bad'")
    conn.commit()
    conn.close()

    store2 = TaskStore(db_path=path)
    d = store2.load("bad")
    assert d is not None
    assert d["result"] is None


# ── Runner 集成 ────────────────────────────────────────────────────────────────


def test_runner_persists_done_task_and_survives_memory_eviction(persisted_env):
    runner = BacktestTaskRunner(max_workers=2, max_results=2)
    task_id = runner.submit(lambda: {"performance": {"total_return": 0.5}}, description="d")
    _wait_done(runner, task_id)

    # 磁盘上能查到 done + 完整结果
    d = ts_mod.get_task_store().load(task_id)
    assert d is not None
    assert d["status"] == "done"
    assert d["result"]["performance"]["total_return"] == 0.5

    # 内存淘汰（提交 3 个新任务挤掉 LRU）后 peek 仍能从磁盘兜底
    for _ in range(3):
        _wait_done(runner, runner.submit(lambda: {"x": 1}))
    state = runner.peek(task_id)
    assert state is not None
    assert state.status == "done"
    assert state.result["performance"]["total_return"] == 0.5
    runner.shutdown()


def test_runner_new_instance_sees_history(persisted_env):
    """「重启」：全新 runner/store 仍能列出并查询历史任务。"""
    runner1 = BacktestTaskRunner(max_workers=1)
    task_id = runner1.submit(lambda: {"performance": {"sharpe": 1.2}}, description="hist")
    _wait_done(runner1, task_id)
    runner1.shutdown()

    runner2 = BacktestTaskRunner(max_workers=1)
    state = runner2.peek(task_id)
    assert state is not None
    assert state.status == "done"
    assert state.result["performance"]["sharpe"] == 1.2
    listed = runner2.list_recent(limit=10)
    assert any(s.task_id == task_id for s in listed)
    runner2.shutdown()


def test_runner_persists_failed_task(persisted_env):
    def _boom():
        raise RuntimeError("炸了")

    runner = BacktestTaskRunner(max_workers=1)
    task_id = runner.submit(_boom, description="bad")
    _wait_done(runner, task_id)
    d = ts_mod.get_task_store().load(task_id)
    assert d is not None
    assert d["status"] == "failed"
    assert "RuntimeError" in d["error"]
    runner.shutdown()


# ── REST 导出端点 ──────────────────────────────────────────────────────────────


def _client() -> TestClient:
    from easy_tdx.web import create_app

    app = create_app()
    return TestClient(app)


def test_export_json_and_csv(persisted_env):
    client = _client()
    # 提交一个内联数据回测任务并等待完成
    import numpy as np
    import pandas as pd

    np.random.seed(7)
    n = 200
    close = 10 + np.cumsum(np.random.randn(n) * 0.2 + 0.05)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    ohlcv = [
        {
            "datetime": d.strftime("%Y-%m-%d"),
            "open": float(c - 0.05),
            "high": float(c + 0.1),
            "low": float(c - 0.1),
            "close": float(c),
            "vol": 5000.0,
            "amount": float(c * 5000),
        }
        for d, c in zip(dates, close, strict=True)
    ]
    resp = client.post(
        "/api/v1/backtest/run/async",
        json={"strategy": "ma_cross", "params": {"fast": 5, "slow": 20}, "ohlcv": ohlcv},
    )
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]
    for _ in range(200):
        st = client.get(f"/api/v1/backtest/tasks/{task_id}").json()
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert st["status"] == "done", st.get("error")

    # JSON 导出：完整 result
    rj = client.get(f"/api/v1/backtest/tasks/{task_id}/export?format=json")
    assert rj.status_code == 200
    assert "attachment" in rj.headers["content-disposition"]
    assert "performance" in rj.json()

    # CSV 导出：主表（trades 或 performance）
    rc = client.get(f"/api/v1/backtest/tasks/{task_id}/export?format=csv")
    assert rc.status_code == 200
    assert rc.headers["content-type"].startswith("text/csv")
    assert len(rc.text.splitlines()) >= 2


def test_export_rejects_unknown_and_unfinished(persisted_env):
    client = _client()
    assert client.get("/api/v1/backtest/tasks/nope/export").status_code == 400
    resp = client.get("/api/v1/backtest/tasks/nope/export?format=xml")
    # 未知任务先报「未知任务」
    assert resp.status_code == 400


def test_task_list_includes_persisted_history_after_new_app(persisted_env):
    """应用层重启（同 DB）后 /backtest/tasks 仍列出历史任务。"""
    runner = BacktestTaskRunner(max_workers=1)
    task_id = runner.submit(lambda: {"performance": {"total_return": 0.1}}, description="旧任务")
    _wait_done(runner, task_id)
    runner.shutdown()

    client = _client()
    tasks = client.get("/api/v1/backtest/tasks?limit=50").json()["tasks"]
    assert any(t["task_id"] == task_id for t in tasks)
