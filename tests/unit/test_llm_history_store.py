"""AI 解读历史存储测试（llm_history_store.py，v1.29）。"""

from __future__ import annotations

import pytest

from easy_tdx.web.llm_history_store import LlmHistoryRecord, LlmHistoryStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path))
    return LlmHistoryStore()


def _rec(**kw) -> LlmHistoryRecord:
    base = dict(provider="zhipu", model="glm-5.3-flash", prompt="报告…", reply="解读…")
    base.update(kw)
    return LlmHistoryRecord(**base)


class TestLlmHistoryStore:
    def test_add_and_list_newest_first(self, store):
        store.add(_rec(reply="第一条"))
        store.add(_rec(reply="第二条"))
        items = store.list_all()
        assert len(items) == 2
        assert items[0].reply == "第二条"  # 倒序
        assert items[0].id is not None and items[0].created_at

    def test_context_roundtrip(self, store):
        store.add(
            _rec(
                strategy="zig_breakout",
                strategy_label="ZIG 右侧突破回补",
                symbol="600519",
                category="DAY",
                params={"zig_delta": 5.0, "confirm_pct": 2.0},
                start_date="2024-01-01",
                end_date="2025-01-01",
            )
        )
        it = store.list_all()[0]
        assert it.strategy == "zig_breakout" and it.symbol == "600519"
        assert it.params == {"zig_delta": 5.0, "confirm_pct": 2.0}  # JSON 往返保真
        assert it.start_date == "2024-01-01"

    def test_corrupt_params_json_tolerated(self, store, tmp_path):
        store.add(_rec())
        # 手工写坏 params 列，读取不应抛异常
        import sqlite3

        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE llm_history SET params = '{broken'")
        assert store.list_all()[0].params == {}

    def test_delete_and_clear(self, store):
        a = store.add(_rec())
        store.add(_rec())
        assert store.delete(a.id) is True
        assert store.delete(a.id) is False  # 重复删除
        assert len(store.list_all()) == 1
        assert store.clear() == 1
        assert store.list_all() == []

    def test_limit(self, store):
        for i in range(5):
            store.add(_rec(reply=f"r{i}"))
        assert len(store.list_all(limit=3)) == 3
