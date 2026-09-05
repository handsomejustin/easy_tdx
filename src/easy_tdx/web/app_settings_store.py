"""应用级轻量设置（KV，SQLite 持久化，重启不丢）。

与 watchlist/llm_history 同款存储约定：单文件 SQLite 落统一配置目录
（``~/.easy_tdx/settings.db``，随 ``EASY_TDX_CONFIG_DIR`` 走），短连接 +
写锁串行。存放跨重启的服务端偏好，如本地 vipdoc 路径（涨停生态扫描用）。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

__all__ = ["AppSettingsStore", "get_app_settings_store"]

_write_lock = threading.Lock()


def _config_dir() -> Path:
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


class AppSettingsStore:
    """KV 设置存储（值为任意 JSON 可序列化对象，实际以字符串存取）。"""

    def __init__(self, db_path: str | Path | None = None):
        self._path = Path(db_path) if db_path else _config_dir() / "settings.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS settings ("
                    "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, key: str, default: str | None = None) -> str | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return str(row["value"]) if row is not None else default
        finally:
            conn.close()

    def set(self, key: str, value: str) -> None:
        with _write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
                conn.commit()
            finally:
                conn.close()

    def delete(self, key: str) -> None:
        with _write_lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                conn.commit()
            finally:
                conn.close()


_store: AppSettingsStore | None = None
_store_lock = threading.Lock()


def get_app_settings_store() -> AppSettingsStore:
    """进程级单例（测试可通过 ``app_settings_store._store = None`` 重置）。"""
    global _store
    with _store_lock:
        if _store is None:
            _store = AppSettingsStore()
        return _store
