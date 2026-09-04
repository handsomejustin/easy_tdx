"""市场情绪采样持久化（「市场情绪」页的数据后端）。

设计对齐 :mod:`easy_tdx.web.watchlist_store` / :mod:`easy_tdx.web.llm_history_store`：

- 单文件 SQLite，落在统一配置目录（``~/.easy_tdx/sentiment.db``，
  随 ``EASY_TDX_CONFIG_DIR`` 环境变量走）。
- 短连接 + 写锁串行，跨线程/跨事件循环安全。
- 由 :class:`easy_tdx.web.sentiment_sampler.SentimentSampler` 在交易时段每分钟
  采一条全市场广度快照（涨/跌/平/涨停/跌停家数、总成交额），主键 (date, minute)
  幂等写入（采样器重启/重复采样不产生重复行）。
- 查询侧供 ``/market/sentiment/today``（当日分钟曲线）与
  ``/market/sentiment/history``（逐日聚合）使用。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

__all__ = ["SentimentStore", "get_sentiment_store"]

_write_lock = threading.Lock()


def _config_dir() -> Path:
    return Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))


class SentimentStore:
    """情绪采样 SQLite 存储。"""

    def __init__(self, db_path: str | Path | None = None):
        self._path = Path(db_path) if db_path else _config_dir() / "sentiment.db"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS samples (
                        date INTEGER NOT NULL,          -- YYYYMMDD
                        minute INTEGER NOT NULL,        -- HHMM
                        ts INTEGER NOT NULL,            -- epoch 秒
                        up_count INTEGER NOT NULL,
                        down_count INTEGER NOT NULL,
                        neutral_count INTEGER NOT NULL,
                        total_count INTEGER NOT NULL,
                        limit_up_count INTEGER NOT NULL,
                        limit_down_count INTEGER NOT NULL,
                        total_amount REAL NOT NULL,
                        PRIMARY KEY (date, minute)
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_date ON samples(date)")
                conn.commit()
            finally:
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def insert(self, sample: dict[str, Any]) -> None:
        """写入/覆盖一条采样（同 minute 幂等，保留最新值）。"""
        with _write_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO samples (
                        date, minute, ts, up_count, down_count, neutral_count,
                        total_count, limit_up_count, limit_down_count, total_amount
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(sample["date"]),
                        int(sample["minute"]),
                        int(sample["ts"]),
                        int(sample["up_count"]),
                        int(sample["down_count"]),
                        int(sample["neutral_count"]),
                        int(sample["total_count"]),
                        int(sample["limit_up_count"]),
                        int(sample["limit_down_count"]),
                        float(sample["total_amount"]),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def day_samples(self, date: int) -> list[dict[str, Any]]:
        """某交易日的全部分钟采样（按时间升序）。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM samples WHERE date = ? ORDER BY minute",
                (int(date),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def latest_date(self) -> int:
        """最近有采样的交易日（YYYYMMDD），无数据返回 0。"""
        conn = self._connect()
        try:
            row = conn.execute("SELECT MAX(date) AS d FROM samples").fetchone()
            return int(row["d"] or 0)
        finally:
            conn.close()

    def daily_history(self, days: int = 60) -> list[dict[str, Any]]:
        """逐日聚合（近 N 个有采样的交易日，升序）。

        每日输出：收盘快照（当日最后一条采样）的上涨占比/涨跌停家数/成交额，
        以及当日涨停家数峰值（情绪高潮探针）与样本数。
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT c.date                    AS date,
                       c.n                       AS n,
                       c.limit_up_peak           AS limit_up_peak,
                       l.up_count                AS up_count,
                       l.down_count              AS down_count,
                       l.limit_up_close          AS limit_up_close,
                       l.limit_down_close        AS limit_down_close,
                       l.amount_close            AS amount_close
                FROM (
                    SELECT date,
                           COUNT(*) AS n,
                           MAX(limit_up_count) AS limit_up_peak
                    FROM samples GROUP BY date
                ) c
                JOIN (
                    SELECT *
                    FROM (
                        SELECT date,
                               up_count,
                               down_count,
                               limit_up_count  AS limit_up_close,
                               limit_down_count AS limit_down_close,
                               total_amount    AS amount_close,
                               ROW_NUMBER() OVER (
                                   PARTITION BY date ORDER BY minute DESC
                               ) AS rn
                        FROM samples
                    ) WHERE rn = 1
                ) l ON l.date = c.date
                ORDER BY c.date DESC
                LIMIT ?
                """,
                (int(days),),
            ).fetchall()
            out = []
            for r in reversed(rows):
                d = dict(r)
                denom = max(int(d["up_count"]) + int(d["down_count"]), 1)
                d["up_ratio"] = round(100.0 * int(d["up_count"]) / denom, 1)
                out.append(d)
            return out
        finally:
            conn.close()


_store: SentimentStore | None = None
_store_lock = threading.Lock()


def get_sentiment_store() -> SentimentStore:
    """进程级单例（测试可先 set ``sentiment_store._store = None`` 重置）。"""
    global _store
    with _store_lock:
        if _store is None:
            _store = SentimentStore()
        return _store
