"""QFQ 前复权对拍校验（公式法 vs 跳空检测法）。

背景：服务端 QFQ 对长期重度除权股票的深层历史会返回负价，客户端用
``adjust.apply_forward_adjust``（NONE + XDXR 公式法）本地重算兜底。公式法
本身依赖 XDXR 数据完整、字段方向正确——单靠它无法自证可靠（下游项目曾反馈
「茅台负价、浦发除权方向算反」类问题）。

本模块引入第二条独立证据链做交叉验证（借鉴 backtest-system 的思路）：

1. **跳空检测法**：在 NONE 未复权序列上，真实 A 股单日跌幅受涨跌停约束
   （主板 10% / 双创 20% / 北交所 30%）。若某日 ``open`` 相对前一日
   ``close`` 的跌幅超出「跌停幅度 + 余量」，几乎必然是除权造成的假跳空，
   与 XDXR 事件应一一对应。
2. **残差跳空检测**：正确的前复权序列在除权日附近应当价格连续。若复权
   结果在除权日仍残留超出涨跌停约束的跳空，说明复权未生效（漏算事件、
   方向算反或因子错误）。

二者交叉得到四类问题：``bad_price``（非法价格）、``residual_gap``
（复权后除权日仍跳空）、``unexplained_gap``（NONE 跳空但 XDXR 无对应
事件，疑似 XDXR 缺记录）、``wrong_direction``（残差跳空方向与除权相反，
疑似复权方向反了）。

该模块只做检测与报告，不修改数据；调用方（MAC 客户端）据此打日志告警。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "QfqIssue",
    "QfqCrosscheckReport",
    "board_limit_ratio",
    "detect_ex_dividend_gaps",
    "crosscheck_qfq",
]

# 跳空判定余量：真实跌停恰好等于限价（如 -10.0%），除权跳空通常更深；
# 余量用于区分「刚好跌停」与「超出跌停的除权跳空」。
_GAP_MARGIN = 0.005


@dataclass
class QfqIssue:
    """单条对拍问题。"""

    kind: str  # bad_price | residual_gap | unexplained_gap | wrong_direction
    date: str  # YYYY-MM-DD
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "date": self.date, "detail": self.detail}


@dataclass
class QfqCrosscheckReport:
    """对拍报告。``ok`` 为 True 表示未发现三类结构性问题。"""

    symbol: str
    ok: bool
    events_checked: int = 0
    gaps_detected: int = 0
    issues: list[QfqIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ok": self.ok,
            "events_checked": self.events_checked,
            "gaps_detected": self.gaps_detected,
            "issues": [i.to_dict() for i in self.issues],
        }


def board_limit_ratio(code: str, market: int | None = None) -> float:
    """按代码/市场推断涨跌停幅度（返回比例，如 0.10）。

    规则（不含 ST 的 5% 特例——仅凭代码无法识别 ST，且 ST 跌停在 10%
    阈值之内不会造成误报）：

    - 北交所（market==2 或代码 4/8/92 开头）：30%
    - 创业板（30 开头）、科创板（68 开头）：20%
    - 其余（沪深主板）：10%

    Args:
        code: 6 位证券代码。
        market: 通达信市场代码（0=深 1=沪 2=北交所），可选。

    Returns:
        涨跌停幅度比例。
    """
    c = str(code).strip()
    if market == 2 or c.startswith(("4", "8", "92")):
        return 0.30
    if c.startswith(("30", "68")):
        return 0.20
    return 0.10


def _to_dt_index(df: pd.DataFrame) -> pd.Series:
    """把 datetime 列统一为 pd.Timestamp 序列。"""
    return pd.to_datetime(df["datetime"])


def _fmt(dt: Any) -> str:
    """把日期标量格式化为 YYYY-MM-DD。"""
    return str(pd.Timestamp(dt).strftime("%Y-%m-%d"))


def detect_ex_dividend_gaps(
    none_df: pd.DataFrame,
    code: str,
    market: int | None = None,
    margin: float = _GAP_MARGIN,
) -> list[str]:
    """在 NONE 未复权序列上检测疑似除权跳空日。

    判定：``open[i] / close[i-1] - 1 < -(limit + margin)``。真实交易中
    单日开盘相对昨收不可能超出跌停幅度（跌停开盘恰好等于 -limit，被余量
    排除），超出即认定为除权造成的价格序列断裂。

    Args:
        none_df: NONE 未复权 K 线（datetime/open/close 列，升序或乱序均可）。
        code: 证券代码（用于推断涨跌停幅度）。
        market: 通达信市场代码（可选）。
        margin: 跳空判定余量（默认 0.5%）。

    Returns:
        疑似除权日列表（YYYY-MM-DD，按时间升序）。
    """
    if none_df is None or len(none_df) < 2 or "open" not in none_df.columns:
        return []
    df = none_df.copy()
    df["_dt"] = _to_dt_index(df)
    df = df.sort_values("_dt").reset_index(drop=True)

    limit = board_limit_ratio(code, market)
    threshold = -(limit + margin)
    prev_close = df["close"].to_numpy(dtype=float)
    open_arr = df["open"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = open_arr[1:] / prev_close[:-1] - 1.0
    out: list[str] = []
    for i in np.where(~np.isfinite(ratio) | (ratio < threshold))[0]:
        out.append(_fmt(df["_dt"].iloc[i + 1]))
    return out


def _xdxr_event_dates(xdxr_df: pd.DataFrame | None) -> list[pd.Timestamp]:
    """提取 XDXR 中 category==1（除权除息）事件的日期（升序去重）。"""
    if xdxr_df is None or xdxr_df.empty:
        return []
    if "category" not in xdxr_df.columns or "date" not in xdxr_df.columns:
        return []
    cat1 = xdxr_df[xdxr_df["category"] == 1]
    dates: list[pd.Timestamp] = []
    for v in cat1["date"]:
        try:
            dates.append(pd.Timestamp(str(v)))
        except (ValueError, TypeError):
            continue
    return sorted(set(dates))


def crosscheck_qfq(
    none_df: pd.DataFrame,
    qfq_df: pd.DataFrame,
    xdxr_df: pd.DataFrame | None,
    code: str,
    market: int | None = None,
    margin: float = _GAP_MARGIN,
) -> QfqCrosscheckReport:
    """对拍校验前复权结果。

    检查项：

    1. ``bad_price``：qfq 序列含 <=0 / NaN / inf 的 OHLC；
    2. ``residual_gap`` / ``wrong_direction``：qfq 序列在 XDXR 除权日仍残留
       超出涨跌停约束的跳空（残差向下 = 复权不足或漏事件；残差向上 =
       复权过度或方向反了）；
    3. ``unexplained_gap``：NONE 序列存在除权跳空，但 ±2 个交易日内无
       XDXR 事件对应（疑似 XDXR 缺记录——公式法此时会漏调该事件）。

    Args:
        none_df: NONE 未复权 K 线（datetime/open/close）。
        qfq_df: 待校验的前复权结果（datetime/open/high/low/close）。
        xdxr_df: ``get_xdxr_info`` 返回的除权除息记录（可为 None）。
        code: 证券代码。
        market: 通达信市场代码（可选）。
        margin: 跳空判定余量。

    Returns:
        :class:`QfqCrosscheckReport`。``ok=False`` 时 ``issues`` 非空。
    """
    symbol = f"{market}:{code}" if market is not None else str(code)
    issues: list[QfqIssue] = []
    limit = board_limit_ratio(code, market)
    threshold = limit + margin

    # ── 1. 非法价格 ───────────────────────────────────────────────────────────
    if qfq_df is not None and len(qfq_df) > 0:
        for col in ("open", "high", "low", "close"):
            if col not in qfq_df.columns:
                continue
            arr = qfq_df[col].to_numpy(dtype=float)
            bad = ~np.isfinite(arr) | (arr <= 0)
            for i in np.where(bad)[0]:
                issues.append(
                    QfqIssue(
                        kind="bad_price",
                        date=_fmt(_to_dt_index(qfq_df).iloc[i]),
                        detail=f"{col} 列第 {int(i)} 根价格非法（{arr[i]}）",
                    )
                )
                break  # 每列报首个即可，避免深层历史批量刷屏

    # ── 2. 除权日残差跳空 ─────────────────────────────────────────────────────
    events_checked = 0
    if qfq_df is not None and len(qfq_df) >= 2:
        q = qfq_df.copy()
        q["_dt"] = _to_dt_index(q)
        q = q.sort_values("_dt").reset_index(drop=True)
        qd = q["_dt"].to_numpy()
        open_arr = q["open"].to_numpy(dtype=float)
        close_arr = q["close"].to_numpy(dtype=float)
        for ed in _xdxr_event_dates(xdxr_df):
            # 事件日（或其后首个交易日）在序列中的位置
            idx = int(np.searchsorted(qd, np.datetime64(ed), side="left"))
            if idx <= 0 or idx >= len(q):
                # 事件在序列范围外（早于首根或晚于末根），无法对拍
                continue
            events_checked += 1
            prev_close = close_arr[idx - 1]
            if prev_close <= 0 or not np.isfinite(prev_close):
                continue
            residual = open_arr[idx] / prev_close - 1.0
            if not np.isfinite(residual):
                issues.append(
                    QfqIssue(
                        kind="residual_gap",
                        date=_fmt(qd[idx]),
                        detail=f"除权日 open={open_arr[idx]} / 昨收={prev_close} 残差非有限",
                    )
                )
            elif residual < -threshold:
                issues.append(
                    QfqIssue(
                        kind="residual_gap",
                        date=_fmt(qd[idx]),
                        detail=(
                            f"除权日仍向下跳空 {residual:.1%}（超阈值 -{threshold:.1%}），"
                            "疑似复权未生效或漏算事件"
                        ),
                    )
                )
            elif residual > threshold:
                issues.append(
                    QfqIssue(
                        kind="wrong_direction",
                        date=_fmt(qd[idx]),
                        detail=(
                            f"除权日向上跳空 {residual:.1%}（超阈值 {threshold:.1%}），"
                            "疑似复权过度或方向算反"
                        ),
                    )
                )

    # ── 3. NONE 跳空 vs XDXR 对应性 ────────────────────────────────────────────
    gaps = detect_ex_dividend_gaps(none_df, code, market, margin)
    gaps_detected = len(gaps)
    if gaps:
        event_dates = _xdxr_event_dates(xdxr_df)
        if none_df is not None and len(none_df) > 0:
            n = none_df.copy()
            n["_dt"] = _to_dt_index(n)
            n = n.sort_values("_dt").reset_index(drop=True)
            nd = n["_dt"].to_numpy()
            for g in gaps:
                gt = np.datetime64(pd.Timestamp(g))
                idx = int(np.searchsorted(nd, gt, side="left"))
                # ±2 个交易日内有事件即视为对应
                lo = max(0, idx - 2)
                hi = min(len(nd), idx + 3)
                matched = any(
                    abs((pd.Timestamp(nd[j]) - pd.Timestamp(g)).days) <= 10
                    and any(abs((e - pd.Timestamp(nd[j])).days) <= 3 for e in event_dates)
                    for j in range(lo, hi)
                )
                if not matched:
                    issues.append(
                        QfqIssue(
                            kind="unexplained_gap",
                            date=g,
                            detail=(
                                "NONE 序列存在超出跌停幅度的向下跳空，"
                                "但 ±2 交易日内无 XDXR 除权事件对应"
                            ),
                        )
                    )

    ok = not any(i.kind in ("bad_price", "residual_gap", "wrong_direction") for i in issues)
    return QfqCrosscheckReport(
        symbol=symbol,
        ok=ok,
        events_checked=events_checked,
        gaps_detected=gaps_detected,
        issues=issues,
    )
