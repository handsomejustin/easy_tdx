"""已保存策略的 SQLite 持久化（用户在 Web UI 上"收藏"的策略 + 成绩快照）。

设计要点：
- 单文件 SQLite，落在项目统一配置目录（``~/.easy_tdx/strategies.db``，
  随 ``EASY_TDX_CONFIG_DIR`` 环境变量走），与 ``config.py`` 同约定。
- 只提供"加入 / 列出 / 查看 / 删除"四个动作（CRUD 中的 CR**D**，不含编辑），
  对应用户诉求："策略能加入，也要能删除"。
- 线程安全：每个公共方法内部 ``with sqlite3.connect(...)`` 短连接，配合
  ``check_same_thread=False`` + 写操作串行（SQLite 单写者锁兜底）。Web 后台
  任务在 ThreadPool 内调用，故默认 ``check_same_thread=False``。
- 表结构简单：单表 ``strategies``，结构化字段建索引，JSON 字段（params /
  context / snapshot）存 TEXT。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "SavedStrategy",
    "StrategyStore",
    "get_store",
]

# 写操作串行锁：SQLite 单写者，多线程并发写时保证一次只进一个事务，避免 "database is locked"。
_write_lock = threading.Lock()


def _config_dir() -> Path:
    """返回统一配置目录（与 config.py 同约定，受 EASY_TDX_CONFIG_DIR 覆盖）。"""
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


def _default_db_path() -> Path:
    return _config_dir() / "strategies.db"


def _now_iso() -> str:
    """UTC ISO8601 时间戳（带 Z 后缀，JSON 友好）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class SavedStrategy:
    """一条已保存策略记录（存配置 + 当时成绩快照 + 上下文）。

    - ``strategy`` + ``params`` 是回测引擎可直接消费的最小可复现形态。
    - ``context`` 记录当时测的是什么（单标的 symbol 或组合 stocks、日期、周期）。
    - ``snapshot`` 记录"为什么觉得它好"（保存时的关键绩效指标）。
    """

    id: str
    name: str
    kind: str  # "single" | "portfolio"
    strategy: str
    strategy_label: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    trade_config: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    app_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "strategy": self.strategy,
            "strategy_label": self.strategy_label,
            "params": self.params,
            "context": self.context,
            "trade_config": self.trade_config,
            "snapshot": self.snapshot,
            "tags": self.tags,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "app_version": self.app_version,
        }

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SavedStrategy:
        """从数据库行构造（JSON 字段反序列化，tags 为 JSON 数组）。"""
        tags = json.loads(row["tags"]) if row["tags"] else []
        return cls(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            strategy=row["strategy"],
            strategy_label=row["strategy_label"] or "",
            params=json.loads(row["params"]) if row["params"] else {},
            context=json.loads(row["context"]) if row["context"] else {},
            trade_config=json.loads(row["trade_config"]) if row["trade_config"] else {},
            snapshot=json.loads(row["snapshot"]) if row["snapshot"] else {},
            tags=tags,
            notes=row["notes"] or "",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            app_version=row["app_version"] or "",
        )


class StrategyStore:
    """已保存策略的 SQLite 存储。

    单例由 :func:`get_store` 提供；测试时可注入独立 ``db_path``（用 tmp_path）。
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS strategies (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        kind            TEXT NOT NULL,
        strategy        TEXT NOT NULL,
        strategy_label  TEXT NOT NULL DEFAULT '',
        params          TEXT NOT NULL DEFAULT '{}',
        context         TEXT NOT NULL DEFAULT '{}',
        trade_config    TEXT NOT NULL DEFAULT '{}',
        snapshot        TEXT NOT NULL DEFAULT '{}',
        tags            TEXT NOT NULL DEFAULT '[]',
        notes           TEXT NOT NULL DEFAULT '',
        created_at      TEXT NOT NULL DEFAULT '',
        updated_at      TEXT NOT NULL DEFAULT '',
        app_version     TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_strategies_kind      ON strategies(kind);
    CREATE INDEX IF NOT EXISTS idx_strategies_strategy  ON strategies(strategy);
    CREATE INDEX IF NOT EXISTS idx_strategies_created   ON strategies(created_at);
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self._ensure_schema()

    # ── 内部 ───────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False：FastAPI 后台任务跑在 ThreadPool 内会跨线程访问。
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(self._SCHEMA)

    @staticmethod
    def _new_id() -> str:
        """生成短 id（uuid4 前 12 位十六进制），足够避免本地单用户碰撞。"""
        return uuid.uuid4().hex[:12]

    # ── 公共 API ───────────────────────────────────────────────────────────

    def add(self, record: SavedStrategy) -> SavedStrategy:
        """加入一条策略记录。``id`` / ``created_at`` / ``updated_at`` 为空时自动填充。"""
        now = _now_iso()
        if not record.id:
            record.id = self._new_id()
        if not record.created_at:
            record.created_at = now
        record.updated_at = now
        with _write_lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO strategies
                   (id, name, kind, strategy, strategy_label, params, context,
                    trade_config, snapshot, tags, notes, created_at, updated_at, app_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.name,
                    record.kind,
                    record.strategy,
                    record.strategy_label,
                    json.dumps(record.params, ensure_ascii=False),
                    json.dumps(record.context, ensure_ascii=False),
                    json.dumps(record.trade_config, ensure_ascii=False),
                    json.dumps(record.snapshot, ensure_ascii=False),
                    json.dumps(record.tags, ensure_ascii=False),
                    record.notes,
                    record.created_at,
                    record.updated_at,
                    record.app_version,
                ),
            )
        return record

    def list_all(self) -> list[SavedStrategy]:
        """列出全部策略，按创建时间倒序（最新保存的在前）。"""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM strategies ORDER BY created_at DESC").fetchall()
        return [SavedStrategy.from_row(r) for r in rows]

    def get(self, strategy_id: str) -> SavedStrategy | None:
        """按 id 查看单条；不存在返回 None。"""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        return SavedStrategy.from_row(row) if row else None

    def delete(self, strategy_id: str) -> bool:
        """按 id 删除；返回是否确实删掉了一条（False = id 不存在）。"""
        with _write_lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            return cur.rowcount > 0


# ── 单例 ───────────────────────────────────────────────────────────────────

_store: StrategyStore | None = None
_store_lock = threading.Lock()


def get_store() -> StrategyStore:
    """返回全局 StrategyStore 单例（首次调用惰性建库）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = StrategyStore()
    return _store
