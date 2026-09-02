"""AI 解读历史持久化（Web UI「AI 解读历史」页的数据后端）。

设计对齐 :mod:`easy_tdx.web.watchlist_store`：

- 单文件 SQLite，落在统一配置目录（``~/.easy_tdx/llm_history.db``，
  随 ``EASY_TDX_CONFIG_DIR`` 环境变量走）。
- 短连接 + 写锁串行，跨线程安全（FastAPI 线程池 / task_runner 工作线程内调用）。
- 每次成功的 AI 解读记一条：Prompt（提问上下文）+ 解读正文 + 模型信息 +
  策略上下文（策略/参数/标的/周期/日期范围）——策略上下文供历史页
  「去回测」一键带参跳转引导。

历史写入属旁路语义：失败不影响解读任务本身（调用方 try/except 兜底）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = ["LlmHistoryRecord", "LlmHistoryStore", "get_llm_history_store"]

_write_lock = threading.Lock()


def _config_dir() -> Path:
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class LlmHistoryRecord:
    """一次成功 AI 解读的完整记录。"""

    provider: str
    model: str
    prompt: str
    reply: str
    elapsed: float = 0.0
    # 策略上下文（「去回测」引导用；手工调用 API 可全部缺省）
    strategy: str = ""
    strategy_label: str = ""
    symbol: str = ""  # 6 位代码（与回测页 code 一致）
    category: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    start_date: str = ""
    end_date: str = ""
    id: int | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "provider": self.provider,
            "model": self.model,
            "prompt": self.prompt,
            "reply": self.reply,
            "elapsed": self.elapsed,
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "symbol": self.symbol,
            "category": self.category,
            "params": self.params,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


class LlmHistoryStore:
    """AI 解读历史 SQLite 存储。单例由 :func:`get_llm_history_store` 提供。"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS llm_history (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at    TEXT NOT NULL,
        provider      TEXT NOT NULL DEFAULT '',
        model         TEXT NOT NULL DEFAULT '',
        prompt        TEXT NOT NULL DEFAULT '',
        reply         TEXT NOT NULL DEFAULT '',
        elapsed       REAL NOT NULL DEFAULT 0,
        strategy      TEXT NOT NULL DEFAULT '',
        strategy_label TEXT NOT NULL DEFAULT '',
        symbol        TEXT NOT NULL DEFAULT '',
        category      TEXT NOT NULL DEFAULT '',
        params        TEXT NOT NULL DEFAULT '{}',
        start_date    TEXT NOT NULL DEFAULT '',
        end_date      TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_llm_history_created ON llm_history(created_at DESC);
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (_config_dir() / "llm_history.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(self._SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, rec: LlmHistoryRecord) -> LlmHistoryRecord:
        """追加一条记录，返回带 id/created_at 的落库结果。"""
        rec.created_at = rec.created_at or _now_iso()
        with _write_lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO llm_history (created_at, provider, model, prompt, reply, elapsed,"
                " strategy, strategy_label, symbol, category, params, start_date, end_date)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.created_at,
                    rec.provider,
                    rec.model,
                    rec.prompt,
                    rec.reply,
                    rec.elapsed,
                    rec.strategy,
                    rec.strategy_label,
                    rec.symbol,
                    rec.category,
                    json.dumps(rec.params, ensure_ascii=False),
                    rec.start_date,
                    rec.end_date,
                ),
            )
            rec.id = int(cur.lastrowid)
        return rec

    def list_all(self, limit: int = 50) -> list[LlmHistoryRecord]:
        """按时间倒序列最近 N 条。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM llm_history ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def delete(self, record_id: int) -> bool:
        """删除一条；返回是否确实删除。"""
        with _write_lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM llm_history WHERE id = ?", (int(record_id),))
            return cur.rowcount > 0

    def clear(self) -> int:
        """清空全部历史；返回删除条数。"""
        with _write_lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM llm_history")
            return cur.rowcount

    @staticmethod
    def _row_to_record(r: sqlite3.Row) -> LlmHistoryRecord:
        try:
            params = json.loads(r["params"] or "{}")
        except json.JSONDecodeError:
            params = {}
        return LlmHistoryRecord(
            id=int(r["id"]),
            created_at=r["created_at"],
            provider=r["provider"],
            model=r["model"],
            prompt=r["prompt"],
            reply=r["reply"],
            elapsed=float(r["elapsed"] or 0),
            strategy=r["strategy"],
            strategy_label=r["strategy_label"],
            symbol=r["symbol"],
            category=r["category"],
            params=params if isinstance(params, dict) else {},
            start_date=r["start_date"],
            end_date=r["end_date"],
        )


_store: LlmHistoryStore | None = None
_store_lock = threading.Lock()


def get_llm_history_store() -> LlmHistoryStore:
    """全局单例（首次调用惰性建库）。"""
    global _store  # noqa: PLW0603 — 模块级单例
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = LlmHistoryStore()
    return _store
