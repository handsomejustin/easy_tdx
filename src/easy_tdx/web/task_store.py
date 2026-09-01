"""回测后台任务的 SQLite 持久化（v1.24 新增）。

此前任务结果只存进程内存（LRU 上限 100），serve 重启即清空——对比页历史、
已完成的寻优排名全部丢失。本模块把任务状态/结果落盘到
``~/.easy_tdx/tasks.db``（随 ``EASY_TDX_CONFIG_DIR`` 走，与 watchlist.db /
strategies.db 同一约定），重启后可继续查询历史任务。

设计对齐 :mod:`easy_tdx.web.strategy_store`：

- 单文件 SQLite，短连接 + 模块级写锁串行（task_runner 工作线程并发写）。
- ``task_id`` 主键，``INSERT OR REPLACE`` 幂等 upsert。
- 结果 JSON 列存 ``serialize_result`` 产出的纯 JSON 字典；防御性
  ``default=`` 兜底 numpy/pandas 残留类型。
- 保留上限 ``_MAX_ROWS``（默认 500，比内存 LRU 的 100 大，磁盘比内存便宜），
  超限按 ``created_at`` 淘汰最旧已完成任务。
- 启动恢复：进程重启后，上个进程遗留的 ``pending/running`` 行标记为
  ``failed``（error 注明「服务重启中断」）——不可能有进程还在跑它们。

测试可通过 ``EASY_TDX_NO_TASK_DB=1`` 环境变量整体关闭持久化（退化为纯内存
行为，兼容旧单测）。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

__all__ = ["TaskStore", "get_task_store"]

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

# 磁盘保留上限：超过后淘汰最旧的 non-pending/running 任务
_MAX_ROWS = 500


def _config_dir() -> Path:
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


def _default_db_path() -> Path:
    return _config_dir() / "tasks.db"


def _json_default(obj: Any) -> Any:
    """json.dumps 防御性兜底：numpy 标量/数组、pd.Timestamp → JSON 原生。"""
    import numpy as np
    import pandas as pd

    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, np.ndarray | pd.Series):
        return obj.tolist()
    return str(obj)


class TaskStore:
    """任务状态/结果的 SQLite 存储。单例由 :func:`get_task_store` 提供。

    线程安全：所有写操作在模块级 ``_write_lock`` 内串行（读也走短连接，
    SQLite 自身 WAL/锁语义可容忍并发读）。
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS backtest_tasks (
        task_id      TEXT PRIMARY KEY,
        status       TEXT NOT NULL,
        description  TEXT NOT NULL DEFAULT '',
        created_at   REAL NOT NULL,
        started_at   REAL,
        finished_at  REAL,
        error        TEXT,
        result_json  TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_backtest_tasks_created
        ON backtest_tasks (created_at DESC);
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._path = Path(db_path) if db_path is not None else _default_db_path()
        self._initialized = False
        self._init_lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """打开短连接；首次调用时建目录与表（``_init_lock`` 防并发双初始化）。

        注意：初始化路径（含中断任务恢复）只依赖 ``_init_lock``，不再获取
        ``_write_lock``——``save`` 在持有 ``_write_lock`` 时会调用本方法，
        若此处再取 ``_write_lock`` 会与非重入锁死锁。
        """
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                    conn = sqlite3.connect(self._path)
                    conn.executescript(self._SCHEMA)
                    conn.commit()
                    conn.close()
                    self._recover_interrupted()
                    self._initialized = True
        return sqlite3.connect(self._path)

    def _recover_interrupted(self) -> None:
        """把上个进程遗留的 pending/running 任务标记为 failed。

        仅在 ``_init_lock`` 内的初始化路径调用（无需再取写锁）。
        """
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.execute(
                """
                UPDATE backtest_tasks
                SET status = 'failed',
                    error = '服务重启，任务中断',
                    finished_at = strftime('%s', 'now')
                WHERE status IN ('pending', 'running')
                """
            )
            if cur.rowcount > 0:
                logger.info("任务持久化：恢复时将 %d 个中断任务标记为 failed", cur.rowcount)
            conn.commit()
        finally:
            conn.close()

    def save(
        self,
        task_id: str,
        status: str,
        description: str = "",
        created_at: float = 0.0,
        started_at: float | None = None,
        finished_at: float | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Upsert 一条任务记录（status/result 任一变化时调用）。"""
        with _write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO backtest_tasks
                        (task_id, status, description, created_at, started_at,
                         finished_at, error, result_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        status,
                        description,
                        created_at,
                        started_at,
                        finished_at,
                        error,
                        json.dumps(result, default=_json_default, ensure_ascii=False)
                        if result is not None
                        else None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            self._evict_if_needed()

    def load(self, task_id: str) -> dict[str, Any] | None:
        """读取单条任务；不存在返回 None。result_json 反序列化进 ``result``。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT task_id, status, description, created_at, started_at,
                       finished_at, error, result_json
                FROM backtest_tasks WHERE task_id = ?
                """,
                (task_id,),
            )
            row = cur.fetchone()
        finally:
            conn.close()
        return self._row_to_dict(row) if row is not None else None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """按 created_at 倒序列出最近 N 条任务摘要（含 result，供详情直取）。"""
        conn = self._connect()
        try:
            cur = conn.execute(
                """
                SELECT task_id, status, description, created_at, started_at,
                       finished_at, error, result_json
                FROM backtest_tasks
                ORDER BY created_at DESC, task_id DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
        finally:
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, task_id: str) -> bool:
        """删除单条任务；返回是否确实删除了。"""
        with _write_lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM backtest_tasks WHERE task_id = ?", (task_id,))
                conn.commit()
            finally:
                conn.close()
            return cur.rowcount > 0

    def _evict_if_needed(self) -> None:
        """超过 _MAX_ROWS 时淘汰最旧的已完成/失败任务（调用方需持写锁）。"""
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.execute("SELECT COUNT(*) FROM backtest_tasks")
            n = int(cur.fetchone()[0])
            if n <= _MAX_ROWS:
                return
            conn.execute(
                """
                DELETE FROM backtest_tasks
                WHERE task_id IN (
                    SELECT task_id FROM backtest_tasks
                    WHERE status IN ('done', 'failed')
                    ORDER BY created_at ASC
                    LIMIT ?
                )
                """,
                (n - _MAX_ROWS,),
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        """行 → 字典；result_json 解析失败时降级为 None 并保留原始文本。"""
        (task_id, status, description, created_at, started_at, finished_at, error, rj) = row
        result: dict[str, Any] | None = None
        if rj is not None:
            try:
                result = json.loads(rj)
            except (TypeError, ValueError):
                logger.warning("任务 %s 的 result_json 解析失败，忽略", task_id)
        return {
            "task_id": task_id,
            "status": status,
            "description": description,
            "created_at": created_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "error": error,
            "result": result,
        }


# ── 全局单例 ───────────────────────────────────────────────────────────────────

_STORE: TaskStore | None = None
_STORE_LOCK = threading.Lock()


def get_task_store() -> TaskStore:
    """获取全局任务存储单例（惰性初始化，线程安全）。

    ``EASY_TDX_NO_TASK_DB=1`` 时返回 DisabledTaskStore 退化实现（所有操作
    no-op / 空），用于测试或显式关闭持久化。
    """
    global _STORE  # noqa: PLW0603 — 模块级单例
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                if os.environ.get("EASY_TDX_NO_TASK_DB") == "1":
                    _STORE = _NullTaskStore()
                else:
                    _STORE = TaskStore()
    return _STORE


def reset_task_store() -> None:
    """重置单例（测试用）。"""
    global _STORE  # noqa: PLW0603
    with _STORE_LOCK:
        _STORE = None


class _NullTaskStore(TaskStore):
    """持久化关闭时的空实现：读返回空、写 no-op。"""

    def __init__(self) -> None:
        super().__init__(db_path=Path(":memory:"))

    def save(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return

    def load(self, task_id: str) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:  # noqa: ARG002
        return []

    def delete(self, task_id: str) -> bool:  # noqa: ARG002
        return False
