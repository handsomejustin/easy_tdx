"""自选股列表的 SQLite 持久化（Web UI"自选"页的数据后端）。

设计对齐 :mod:`easy_tdx.web.strategy_store`：

- 单文件 SQLite，落在统一配置目录（``~/.easy_tdx/watchlist.db``，
  随 ``EASY_TDX_CONFIG_DIR`` 环境变量走）。
- 短连接 + 写锁串行，跨线程安全（FastAPI 线程池内调用）。
- ``(market, code)`` 唯一：重复加入同一只股票幂等（更新名称，不动排序）。
- ``group_name`` 字段预留分组能力，v1 前端未使用，默认 ``"默认"``。
- ``sort_order`` 由插入时 max+1 维持"新加的在最后"，列出时按其升序。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "WatchItem",
    "WatchlistStore",
    "get_watchlist_store",
]

_write_lock = threading.Lock()


def _config_dir() -> Path:
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


def _default_db_path() -> Path:
    return _config_dir() / "watchlist.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class WatchItem:
    """一条自选记录。name 由前端在添加时填好（来自行情/选股接口）。"""

    market: str  # "SH" | "SZ" | "BJ"
    code: str  # 6 位代码
    name: str = ""
    group_name: str = "默认"
    created_at: str = ""
    sort_order: int = 0

    @property
    def symbol(self) -> str:
        """前端统一标识：SH600000 形式。"""
        return f"{self.market}{self.code}"

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "code": self.code,
            "symbol": self.symbol,
            "name": self.name,
            "group_name": self.group_name,
            "created_at": self.created_at,
            "sort_order": self.sort_order,
        }


class WatchlistStore:
    """自选股 SQLite 存储。单例由 :func:`get_watchlist_store` 提供。"""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS watchlist (
        market      TEXT NOT NULL,
        code        TEXT NOT NULL,
        name        TEXT NOT NULL DEFAULT '',
        group_name  TEXT NOT NULL DEFAULT '默认',
        created_at  TEXT NOT NULL DEFAULT '',
        sort_order  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (market, code)
    );
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(self._SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def list_all(self, group: str | None = None) -> list[WatchItem]:
        """列出全部自选（按 sort_order 升序），可按分组过滤。"""
        with self._connect() as conn:
            if group:
                rows = conn.execute(
                    "SELECT * FROM watchlist WHERE group_name = ? ORDER BY sort_order",
                    (group,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM watchlist ORDER BY sort_order").fetchall()
        return [
            WatchItem(
                market=r["market"],
                code=r["code"],
                name=r["name"],
                group_name=r["group_name"],
                created_at=r["created_at"],
                sort_order=r["sort_order"],
            )
            for r in rows
        ]

    def symbols(self) -> list[tuple[str, str]]:
        """列出 (market, code) 元组——SSE 轮询器订阅集合用。"""
        return [(i.market, i.code) for i in self.list_all()]

    def add(self, market: str, code: str, name: str = "", group: str = "默认") -> WatchItem:
        """加入自选；已存在时幂等返回（仅刷新名称）。"""
        market = market.upper()
        with _write_lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM watchlist WHERE market = ? AND code = ?",
                (market, code),
            ).fetchone()
            if row is not None:
                if name and name != row["name"]:
                    conn.execute(
                        "UPDATE watchlist SET name = ? WHERE market = ? AND code = ?",
                        (name, market, code),
                    )
                return WatchItem(
                    market=row["market"],
                    code=row["code"],
                    name=name or row["name"],
                    group_name=row["group_name"],
                    created_at=row["created_at"],
                    sort_order=row["sort_order"],
                )
            next_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM watchlist"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO watchlist (market, code, name, group_name, created_at, sort_order)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (market, code, name, group, _now_iso(), next_order),
            )
        return WatchItem(
            market=market,
            code=code,
            name=name,
            group_name=group,
            created_at=_now_iso(),
            sort_order=next_order,
        )

    def remove(self, market: str, code: str) -> bool:
        """移除自选；返回是否确实删除了一条。"""
        market = market.upper()
        with _write_lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM watchlist WHERE market = ? AND code = ?", (market, code)
            )
            return cur.rowcount > 0


_store: WatchlistStore | None = None
_store_lock = threading.Lock()


def get_watchlist_store() -> WatchlistStore:
    """全局单例（首次调用惰性建库）。"""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = WatchlistStore()
    return _store
