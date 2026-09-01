"""K 线本地数据仓库（DuckDB，v1.26 新增）。

此前 easy-tdx 的缓存是碎片化的（股票列表缓存 / best_host / 进程内 XDXR
字典 / 扫描 JSON），没有统一的 K 线磁盘层——下游项目（indicator-lab 的
DuckDB 仓库、backtest-system 的 cache/ 目录）都在自建数据层。本模块把
「拉过的行情」沉淀为本地列存仓库：

- **单文件 DuckDB**（默认 ``~/.easy_tdx/warehouse.duckdb``，随
  ``EASY_TDX_CONFIG_DIR`` 走）：零服务、列存、SQL 友好、压缩率高
  （万只标的十年日线约几百 MB）；
- **增量同步**：每标的只补最后若干根（首同步全量拉取），同日 bar 用新值
  覆盖（收盘修正），历史数据不动；
- **provisional / completed 状态机**（借鉴 indicator-lab）：15:05 前落盘
  的当日 bar 标记 ``provisional``（未收盘的临时值），查询/回测**默认忽略**，
  只在显式 ``include_provisional=True`` 时可见；次日增量同步自动把过期
  临时行转正/覆盖。

DuckDB 为可选依赖（``pip install easy-tdx[warehouse]``），惰性导入——
未安装时本模块给出明确报错，不影响核心三通道。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from datetime import time as dt_time
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["KlineWarehouse", "default_warehouse_path", "MARKET_TO_TDX"]

# 未收盘 cutoff：15:05（A股 15:00 收盘 + 5 分钟数据落定余量）
_MARKET_CLOSE_CUTOFF = dt_time(15, 5)

MARKET_TO_TDX: dict[str, int] = {"SZ": 0, "SH": 1, "BJ": 2}
_TDX_TO_MARKET: dict[int, str] = {v: k for k, v in MARKET_TO_TDX.items()}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS klines (
    market     TEXT NOT NULL,
    code       TEXT NOT NULL,
    period     TEXT NOT NULL,
    datetime   TIMESTAMP NOT NULL,
    open       DOUBLE,
    high       DOUBLE,
    low        DOUBLE,
    close      DOUBLE,
    vol        DOUBLE,
    amount     DOUBLE,
    status     TEXT NOT NULL DEFAULT 'completed',
    updated_at TIMESTAMP,
    PRIMARY KEY (market, code, period, datetime)
);
CREATE INDEX IF NOT EXISTS idx_klines_symbol ON klines (market, code, period, datetime);
"""


def default_warehouse_path() -> Path:
    """默认仓库文件路径（随 ``EASY_TDX_CONFIG_DIR``）。"""
    import os

    base = Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))
    return base / "warehouse.duckdb"


def _require_duckdb() -> Any:
    try:
        import duckdb  # noqa: PLC0415 — 惰性导入，可选依赖
    except ImportError as exc:
        raise ImportError(
            "warehouse 功能需要 DuckDB：pip install easy-tdx[warehouse]（或 pip install duckdb）"
        ) from exc
    return duckdb


class KlineWarehouse:
    """K 线 DuckDB 仓库：upsert / 查询 / provisional 状态机 / 健康自检。

    Example::
        wh = KlineWarehouse()               # 或 KlineWarehouse(path)
        wh.upsert_bars("SH", "600519", df)  # 增量写入
        df = wh.query("SH", "600519", count=250)  # 默认忽略 provisional
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._duckdb = _require_duckdb()
        self._path = Path(db_path) if db_path is not None else default_warehouse_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._duckdb.connect(str(self._path))
        self._conn.execute(_SCHEMA)

    # ── 基本属性 ─────────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        """关闭连接。"""
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001 — 幂等关闭
            pass

    def __enter__(self) -> KlineWarehouse:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── 写入 ─────────────────────────────────────────────────────────────────

    def upsert_bars(
        self,
        market: str,
        code: str,
        df: pd.DataFrame,
        period: str = "DAILY",
        status: str | None = None,
    ) -> tuple[int, int]:
        """Upsert 一批 K 线，返回 ``(新增数, 更新数)``。

        Args:
            market: ``"SH"`` / ``"SZ"`` / ``"BJ"``。
            code: 6 位代码。
            df: 含 ``datetime``（或 ``date``）与 OHLCV 列的 K 线。
            period: 周期名（默认 ``"DAILY"``，与 Period 名对齐）。
            status: 显式状态；None = 自动（当日 bar 且未过 15:05 →
                ``provisional``，其余 ``completed``）。
        """
        if df is None or len(df) == 0:
            return (0, 0)
        mkt = market.upper()
        src = df.copy()
        dt_col = "datetime" if "datetime" in src.columns else "date"
        src["_dt"] = pd.to_datetime(src[dt_col])
        cols = ["open", "high", "low", "close", "vol", "amount"]
        for c in cols:
            if c not in src.columns:
                src[c] = float("nan")

        now = datetime.now()
        today = now.date()
        before_close = now.time() < _MARKET_CLOSE_CUTOFF

        def _row_status(ts: pd.Timestamp) -> str:
            """逐行判定：当日 bar 且未过 15:05 → provisional，否则 completed。"""
            if status is not None:
                return status
            return "provisional" if (ts.date() == today and before_close) else "completed"

        # 统计新增/更新（按已有键）
        existing = self._conn.execute(
            """
            SELECT datetime FROM klines
            WHERE market = ? AND code = ? AND period = ?
              AND datetime >= ?
            """,
            [mkt, code, period, src["_dt"].min().to_pydatetime()],
        ).fetchall()
        existing_keys = {row[0] for row in existing}

        rows = []
        for _, r in src.iterrows():
            ts = r["_dt"]
            rows.append(
                (
                    mkt,
                    code,
                    period,
                    ts.to_pydatetime(),
                    float(r["open"]),
                    float(r["high"]),
                    float(r["low"]),
                    float(r["close"]),
                    float(r["vol"]),
                    float(r["amount"]),
                    _row_status(ts),
                    now,
                )
            )
        self._conn.executemany(
            """
            INSERT INTO klines (market, code, period, datetime, open, high, low,
                                close, vol, amount, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (market, code, period, datetime) DO UPDATE SET
                open = excluded.open, high = excluded.high, low = excluded.low,
                close = excluded.close, vol = excluded.vol, amount = excluded.amount,
                status = excluded.status, updated_at = excluded.updated_at
            """,
            rows,
        )
        # DuckDB timestamp 精度：统一到秒级比较
        existing_sec = {ts.replace(microsecond=0) for ts in existing_keys}
        inserted = sum(1 for r in rows if r[3].replace(microsecond=0) not in existing_sec)
        updated = len(rows) - inserted
        return (inserted, updated)

    def promote_provisional(self) -> int:
        """把「日期已过」的 provisional 行转正（收盘后的临时值已被次日增量覆盖）。"""
        today = datetime.now().date()
        cur = self._conn.execute(
            """
            UPDATE klines SET status = 'completed'
            WHERE status = 'provisional' AND CAST(datetime AS DATE) < ?
            """,
            [today],
        )
        return int(cur.fetchone()[0]) if cur.description else 0

    # ── 查询 ─────────────────────────────────────────────────────────────────

    def query(
        self,
        market: str,
        code: str,
        period: str = "DAILY",
        start: str | None = None,
        end: str | None = None,
        count: int | None = None,
        include_provisional: bool = False,
    ) -> pd.DataFrame:
        """查询 K 线（时间升序），返回 pandas DataFrame。

        Args:
            start / end: 日期范围（``YYYY-MM-DD``，闭区间，可选）。
            count: 只取最近 N 根（在过滤后应用）。
            include_provisional: False（默认）时忽略未收盘的临时 bar——
                筛选/回测默认口径，杜绝拿盘中价当收盘价。
        """
        mkt = market.upper()
        conds = ["market = ?", "code = ?", "period = ?"]
        params: list[Any] = [mkt, code, period]
        if not include_provisional:
            conds.append("status = 'completed'")
        if start:
            conds.append("CAST(datetime AS DATE) >= ?")
            params.append(start)
        if end:
            conds.append("CAST(datetime AS DATE) <= ?")
            params.append(end)
        where = " AND ".join(conds)
        if count is not None:
            df = self._conn.execute(
                f"""
                SELECT * FROM (
                    SELECT * FROM klines WHERE {where}
                    ORDER BY datetime DESC LIMIT ?
                ) ORDER BY datetime ASC
                """,
                [*params, int(count)],
            ).df()
        else:
            df = self._conn.execute(
                f"SELECT * FROM klines WHERE {where} ORDER BY datetime ASC", params
            ).df()
        return df

    def last_datetime(
        self,
        market: str,
        code: str,
        period: str = "DAILY",
        include_provisional: bool = True,
    ) -> pd.Timestamp | None:
        """该标的最新 bar 时间（无数据返回 None）。"""
        mkt = market.upper()
        cond = "" if include_provisional else "AND status = 'completed'"
        row = self._conn.execute(
            f"""
            SELECT max(datetime) FROM klines
            WHERE market = ? AND code = ? AND period = ? {cond}
            """,
            [mkt, code, period],
        ).fetchone()
        val = row[0] if row else None
        return pd.Timestamp(val) if val is not None else None

    def symbols(self, period: str = "DAILY") -> pd.DataFrame:
        """列出仓库内全部标的及其数据范围/行数。"""
        return self._conn.execute(
            """
            SELECT market, code, count(*) AS bars,
                   min(datetime) AS first, max(datetime) AS last,
                   sum(CASE WHEN status = 'provisional' THEN 1 ELSE 0 END) AS provisional
            FROM klines WHERE period = ?
            GROUP BY market, code ORDER BY market, code
            """,
            [period],
        ).df()

    # ── 删除 ─────────────────────────────────────────────────────────────────

    def delete_symbol(self, market: str, code: str, period: str = "DAILY") -> int:
        """删除某标的全部数据，返回删除行数。"""
        cur = self._conn.execute(
            "DELETE FROM klines WHERE market = ? AND code = ? AND period = ?",
            [market.upper(), code, period],
        )
        n = cur.fetchone()[0] if cur.description else 0
        return int(n)

    # ── 健康自检（P2-3）──────────────────────────────────────────────────────

    def health_check(
        self,
        market: str | None = None,
        code: str | None = None,
        max_gap_weekdays: int = 5,
    ) -> dict[str, Any]:
        """仓库健康自检：缺口 / 异常跳变 / 最新度 / 临时行统计。

        Args:
            market / code: 只检查指定标的（None = 全仓库）。
            max_gap_weekdays: 相邻 bar 间缺失「交易日数」超过该值报疑似缺口
                （节假日会造成少量误报，报告口径为「待人工核查」）。

        Returns:
            ``{"symbols_checked", "issues": [...], "summary": {...}}``。
        """
        from easy_tdx.mac.qfq_check import detect_ex_dividend_gaps

        conds = ["period = 'DAILY'"]
        params: list[Any] = []
        if market is not None:
            conds.append("market = ?")
            params.append(market.upper())
        if code is not None:
            conds.append("code = ?")
            params.append(code)
        where = " AND ".join(conds)

        sym_df = self._conn.execute(
            f"""
            SELECT market, code, count(*) AS bars,
                   min(datetime) AS first, max(datetime) AS last,
                   sum(CASE WHEN status = 'provisional' THEN 1 ELSE 0 END) AS provisional
            FROM klines WHERE {where}
            GROUP BY market, code
            """,
            params,
        ).df()

        issues: list[dict[str, Any]] = []
        today = date.today()
        stale: list[dict[str, Any]] = []
        total_provisional = 0

        for _, s in sym_df.iterrows():
            mkt, cde = str(s["market"]), str(s["code"])
            total_provisional += int(s["provisional"])

            # 最新度
            last = pd.Timestamp(s["last"])
            stale_days = (today - last.date()).days
            if stale_days > 7:
                stale.append(
                    {"symbol": f"{mkt}:{cde}", "last": str(last.date()), "days": stale_days}
                )

            # 缺口：相邻 bar 的「工作日差」
            df = self.query(mkt, cde, include_provisional=True)
            if len(df) < 2:
                continue
            dts = pd.to_datetime(df["datetime"]).dt.date
            gaps = []
            for prev, cur_d in zip(dts.iloc[:-1], dts.iloc[1:], strict=False):
                weekdays = np_busdays(prev, cur_d)
                if weekdays > max_gap_weekdays:
                    gaps.append(
                        {"after": str(prev), "before": str(cur_d), "weekdays": int(weekdays)}
                    )
            if gaps:
                issues.append(
                    {
                        "symbol": f"{mkt}:{cde}",
                        "kind": "gap",
                        "detail": (
                            f"{len(gaps)} 处疑似缺口（缺失工作日>{max_gap_weekdays}，含节假日误报）"
                        ),
                        "gaps": gaps[:10],
                    }
                )

            # 异常跳变（板块感知阈值，复用 QFQ 对拍的跳空检测）
            jump_dates = detect_ex_dividend_gaps(df, cde, MARKET_TO_TDX.get(mkt))
            if jump_dates:
                issues.append(
                    {
                        "symbol": f"{mkt}:{cde}",
                        "kind": "price_jump",
                        "detail": (
                            f"{len(jump_dates)} 处超出跌停幅度的向下跳空"
                            "（多为除权，未复权数据需人工核查）"
                        ),
                        "dates": jump_dates[:10],
                    }
                )

        return {
            "symbols_checked": int(len(sym_df)),
            "issues": issues,
            "summary": {
                "symbols_with_issues": len({i["symbol"] for i in issues}),
                "stale_symbols": stale[:20],
                "provisional_rows": total_provisional,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            },
        }


def np_busdays(d1: date, d2: date) -> int:
    """两个日期之间的工作日数（不含首日，含规则近似：周一~周五）。"""
    import numpy as _np

    if d2 <= d1:
        return 0
    return int(_np.busday_count(d1, d2))
