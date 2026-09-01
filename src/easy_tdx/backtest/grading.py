"""数据评级系统（S/A/B/C/D）的 Python 后端实现（v1.25 新增）。

移植自 ``web-ui/src/grading/``（engine.ts / thresholds.ts / index.ts /
combinedMetrics.ts）——此前评级只存在于前端 TS，CLI 与 REST API 无法输出。
本模块与其保持口径一致（对拍单测保证），三通道均可获得评级。

评级哲学（同前端）：**不看收益率**。收益维度只通过卡玛/夏普间接体现，
「哪怕近期收益率高，长期风险大也该低评」。六维加权（单标的场景）+
一票否决（亏损系统 / 深度套牢 / 极低胜率 / 高回撤 / 微利）。

场景：

- :func:`grade_performance`：单标的回测（完整 19 项绩效，6 维度）
- :func:`grade_grid_point`：参数寻优网格点（4 字段子集，4 维度降级版）
- :func:`grade_portfolio_equity`：组合回测（净值曲线重算，5 维度）

阈值锚点集中在本文件 ``THRESHOLDS``，与前端 thresholds.ts 一一对应；
两处需同步修改时以对拍单测（``test_grading_backend.py``）为门禁。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "Grade",
    "Anchor",
    "DimensionScore",
    "VetoHit",
    "GradeResult",
    "CombinedMetrics",
    "compute_combined_metrics",
    "interpolate",
    "score_to_grade",
    "grade_performance",
    "grade_grid_point",
    "grade_portfolio_equity",
]

Grade = Literal["S", "A", "B", "C", "D"]

_TRADING_DAYS_PER_YEAR = 252

# 档位 → 最低分（score_to_grade）
_GRADE_THRESHOLDS: list[tuple[Grade, float]] = [
    ("S", 90.0),
    ("A", 80.0),
    ("B", 65.0),
    ("C", 50.0),
    ("D", 0.0),
]

_GRADE_ORDER: list[Grade] = ["D", "C", "B", "A", "S"]


@dataclass(frozen=True)
class Anchor:
    """(指标原始值, 对应分数) 锚点，线性插值用。"""

    threshold: float
    score: float


# 阈值锚点表（与前端 thresholds.ts 一一对应，勿单侧修改）
THRESHOLDS: dict[str, tuple[str, tuple[Anchor, ...]]] = {
    "calmar": (
        "卡玛比率",
        (
            Anchor(0.0, 0),
            Anchor(0.3, 20),
            Anchor(0.5, 35),
            Anchor(0.8, 50),
            Anchor(1.0, 65),
            Anchor(1.5, 80),
            Anchor(2.0, 90),
            Anchor(3.0, 100),
        ),
    ),
    "sharpe": (
        "夏普比率",
        (
            Anchor(0.0, 10),
            Anchor(0.3, 25),
            Anchor(0.5, 40),
            Anchor(0.8, 55),
            Anchor(1.0, 68),
            Anchor(1.5, 82),
            Anchor(2.0, 92),
            Anchor(3.0, 100),
        ),
    ),
    "sortino": (
        "索提诺比率",
        (
            Anchor(0.0, 10),
            Anchor(0.5, 30),
            Anchor(1.0, 50),
            Anchor(1.5, 65),
            Anchor(2.0, 78),
            Anchor(2.5, 88),
            Anchor(4.0, 100),
        ),
    ),
    "max_drawdown": (
        "最大回撤",
        (
            Anchor(0.0, 100),
            Anchor(0.1, 88),
            Anchor(0.15, 78),
            Anchor(0.2, 68),
            Anchor(0.25, 58),
            Anchor(0.3, 48),
            Anchor(0.4, 30),
            Anchor(0.5, 15),
            Anchor(0.6, 0),
        ),
    ),
    "volatility": (
        "波动率",
        (
            Anchor(0.0, 100),
            Anchor(0.1, 85),
            Anchor(0.15, 75),
            Anchor(0.2, 62),
            Anchor(0.25, 50),
            Anchor(0.3, 38),
            Anchor(0.4, 22),
            Anchor(0.6, 0),
        ),
    ),
    "max_dd_duration": (
        "回撤持续",
        (
            Anchor(0, 100),
            Anchor(30, 80),
            Anchor(90, 62),
            Anchor(180, 45),
            Anchor(365, 28),
            Anchor(730, 10),
            Anchor(1095, 0),
        ),
    ),
    "win_rate": (
        "胜率",
        (
            Anchor(0.0, 0),
            Anchor(0.25, 12),
            Anchor(0.3, 22),
            Anchor(0.35, 32),
            Anchor(0.4, 45),
            Anchor(0.45, 58),
            Anchor(0.5, 70),
            Anchor(0.55, 82),
            Anchor(0.6, 92),
            Anchor(0.7, 100),
        ),
    ),
    "profit_factor": (
        "利润因子",
        (
            Anchor(0.0, 0),
            Anchor(0.8, 10),
            Anchor(1.0, 25),
            Anchor(1.2, 42),
            Anchor(1.5, 60),
            Anchor(1.8, 75),
            Anchor(2.0, 84),
            Anchor(2.5, 92),
            Anchor(3.0, 100),
        ),
    ),
}


@dataclass
class DimensionScore:
    """单个评分维度。"""

    key: str
    label: str
    raw: float
    score: float
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "raw": self.raw,
            "score": round(self.score, 1),
            "weight": round(self.weight, 4),
        }


@dataclass
class VetoHit:
    """触发的一票否决规则。"""

    key: str
    reason: str
    cap: Grade

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "reason": self.reason, "cap": self.cap}


@dataclass
class GradeResult:
    """评级结果。"""

    grade: Grade
    score: float  # 0-100，保留 1 位小数的加权原始分
    dimensions: list[DimensionScore] = field(default_factory=list)
    vetoes: list[VetoHit] = field(default_factory=list)
    insufficient_sample: bool = False
    is_losing: bool = False
    scenario: str = "single"

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "score": self.score,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "vetoes": [v.to_dict() for v in self.vetoes],
            "insufficient_sample": self.insufficient_sample,
            "is_losing": self.is_losing,
            "scenario": self.scenario,
        }


# ── 插值与基础函数（对应 engine.ts）──────────────────────────────────────────


def interpolate(anchors: Iterable[Anchor], value: float) -> float:
    """按锚点列表做线性插值，返回 0-100 分。值越界取端点。"""
    arr = list(anchors)
    if not arr or not math.isfinite(value):
        return 0.0
    if value <= arr[0].threshold:
        return float(arr[0].score)
    if value >= arr[-1].threshold:
        return float(arr[-1].score)
    for a, b in zip(arr, arr[1:], strict=False):
        if a.threshold <= value <= b.threshold:
            if a.threshold == b.threshold:
                return float(a.score)
            ratio = (value - a.threshold) / (b.threshold - a.threshold)
            return float(a.score + ratio * (b.score - a.score))
    return float(arr[-1].score)


def score_dimension(key: str, raw: float, weight: float) -> DimensionScore:
    """构造维度评分对象。"""
    label, anchors = THRESHOLDS[key]
    return DimensionScore(
        key=key, label=label, raw=float(raw), score=interpolate(anchors, raw), weight=weight
    )


def weighted_total(dimensions: list[DimensionScore]) -> float:
    """加权求和（权重在调用方归一化）。"""
    total_weight = sum(d.weight for d in dimensions)
    if total_weight <= 0:
        return 0.0
    return sum(d.score * d.weight for d in dimensions) / total_weight


def score_to_grade(score: float) -> Grade:
    """分数 → 档位（不考虑否决）。"""
    for grade, min_score in _GRADE_THRESHOLDS:
        if score >= min_score:
            return grade
    return "D"


def _worse_grade(a: Grade, b: Grade) -> Grade:
    """取两个档位中更差者。"""
    return a if _GRADE_ORDER.index(a) <= _GRADE_ORDER.index(b) else b


def _build_result(
    scenario: str,
    dimensions: list[DimensionScore],
    vetoes: list[VetoHit],
    insufficient_sample: bool,
    is_losing: bool,
) -> GradeResult:
    raw_score = weighted_total(dimensions)
    grade = score_to_grade(raw_score)
    for v in vetoes:
        grade = _worse_grade(grade, v.cap)
    return GradeResult(
        grade=grade,
        score=round(raw_score * 10) / 10,
        dimensions=dimensions,
        vetoes=vetoes,
        insufficient_sample=insufficient_sample,
        is_losing=is_losing,
        scenario=scenario,
    )


# ── 一票否决（对应 index.ts applyVetoes）─────────────────────────────────────


def _apply_vetoes(
    profit_factor: float | None = None,
    total_trades: int | None = None,
    max_drawdown: float | None = None,
    win_rate: float | None = None,
) -> tuple[list[VetoHit], bool, bool]:
    """应用一票否决规则。返回 (否决列表, 样本不足, 系统亏损)。"""
    vetoes: list[VetoHit] = []
    insufficient_sample = False
    is_losing = False

    if profit_factor is not None and profit_factor < 1:
        vetoes.append(
            VetoHit(
                key="losing_system",
                reason=f"利润因子 {profit_factor:.2f} < 1，系统实际亏损",
                cap="D",
            )
        )
        is_losing = True

    if total_trades is not None and total_trades < 10:
        insufficient_sample = True

    if max_drawdown is not None and max_drawdown > 0.6:
        vetoes.append(
            VetoHit(
                key="deep_drawdown",
                reason=f"最大回撤 {max_drawdown * 100:.1f}% > 60%，深度套牢几乎无法回本",
                cap="D",
            )
        )

    enough_trades = total_trades is None or total_trades >= 10
    if enough_trades and win_rate is not None and win_rate < 0.25:
        vetoes.append(
            VetoHit(
                key="very_low_winrate",
                reason=f"胜率 {win_rate * 100:.1f}% < 25% 且样本充足，几乎一直亏",
                cap="D",
            )
        )
    if max_drawdown is not None and max_drawdown > 0.5:
        vetoes.append(
            VetoHit(
                key="high_drawdown",
                reason=f"最大回撤 {max_drawdown * 100:.1f}% > 50%，套牢难回本",
                cap="B",
            )
        )
    if enough_trades and win_rate is not None and 0.25 <= win_rate < 0.3:
        vetoes.append(
            VetoHit(
                key="low_winrate",
                reason=f"胜率 {win_rate * 100:.1f}% < 30% 且样本充足，普通人拿不住",
                cap="C",
            )
        )
    if profit_factor is not None and 1 <= profit_factor < 1.2:
        vetoes.append(
            VetoHit(
                key="thin_edge",
                reason=f"利润因子 {profit_factor:.2f} 接近 1，仅勉强盈亏平衡",
                cap="B",
            )
        )
    return vetoes, insufficient_sample, is_losing


def _downweight_unreliable(dimensions: list[DimensionScore]) -> bool:
    """样本不足时把 win_rate / profit_factor 权重降 0，按比例重分配。"""
    keys = {"win_rate", "profit_factor"}
    to_down = [d for d in dimensions if d.key in keys]
    if not to_down:
        return False
    released = sum(d.weight for d in to_down)
    if released <= 0:
        return False
    for d in to_down:
        d.weight = 0.0
    receivers = [d for d in dimensions if d.weight > 0]
    if not receivers:
        return False
    receiver_total = sum(d.weight for d in receivers)
    for d in receivers:
        d.weight += released * (d.weight / receiver_total)
    return True


# ── 组合净值指标重算（对应 combinedMetrics.ts）────────────────────────────────


@dataclass
class CombinedMetrics:
    """从净值序列重算的组合级指标（净值可推导的字段子集）。"""

    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    max_dd_duration: int = 0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    volatility: float = 0.0
    n_points: int = 0
    years: float = 0.0


def compute_combined_metrics(equity: list[dict[str, Any]]) -> CombinedMetrics:
    """从组合净值曲线重算绩效指标（与前端 computeCombinedMetrics 同口径）。

    Args:
        equity: 净值点列表（按时间升序），每点含 ``total``（= cash +
            position_value），可选 ``datetime`` / ``drawdown_pct``。

    Returns:
        :class:`CombinedMetrics`。数据不足（<2 点）时字段全 0。
    """
    import numpy as np

    n = len(equity)
    if n < 2:
        return CombinedMetrics(n_points=n)

    totals = [float(e["total"]) for e in equity]
    start_v, end_v = totals[0], totals[-1]
    total_return = end_v / start_v - 1 if start_v > 0 else 0.0

    years = n / _TRADING_DAYS_PER_YEAR
    try:
        import pandas as pd

        first = pd.Timestamp(str(equity[0].get("datetime", "")))
        last = pd.Timestamp(str(equity[-1].get("datetime", "")))
        span_days = (last - first).total_seconds() / 86400.0
        if span_days > 0:
            years = span_days / 365.25
    except (ValueError, TypeError):
        pass
    annual_return = (end_v / start_v) ** (1.0 / years) - 1 if years > 0 and start_v > 0 else 0.0

    arr = np.array(totals, dtype=float)
    prev = arr[:-1]
    cur = arr[1:]
    mask = prev > 0
    rets = cur[mask] / prev[mask] - 1.0
    mean_r = float(np.mean(rets)) if len(rets) else 0.0
    std_r = float(np.std(rets, ddof=1)) if len(rets) >= 2 else 0.0
    volatility = std_r * math.sqrt(_TRADING_DAYS_PER_YEAR)
    sharpe = mean_r / std_r * math.sqrt(_TRADING_DAYS_PER_YEAR) if std_r > 0 else 0.0
    downside = rets[rets < 0]
    downside_std = float(np.sqrt(np.mean(downside**2))) if len(downside) else 0.0
    sortino = mean_r / downside_std * math.sqrt(_TRADING_DAYS_PER_YEAR) if downside_std > 0 else 0.0

    # 最大回撤 & 持续：优先用 drawdown_pct（与前端一致），缺则从 totals 反推
    max_dd = 0.0
    max_dd_dur = 0
    if equity[0].get("drawdown_pct") is not None:
        cur_peak = 0
        for i, e in enumerate(equity):
            dd = float(e.get("drawdown_pct") or 0.0)
            if dd > max_dd:
                max_dd = dd
                max_dd_dur = i - cur_peak
            if dd == 0:
                cur_peak = i
    else:
        running_peak = totals[0]
        cur_peak = 0
        for i, v in enumerate(totals):
            if v > running_peak:
                running_peak = v
                cur_peak = i
            if running_peak > 0:
                dd_pct = (running_peak - v) / running_peak
                if dd_pct > max_dd:
                    max_dd = dd_pct
                    max_dd_dur = i - cur_peak

    if max_dd > 0:
        calmar = annual_return / max_dd
    else:
        calmar = 999.0 if annual_return > 0 else 0.0

    return CombinedMetrics(
        total_return=total_return,
        annual_return=annual_return,
        max_drawdown=max_dd,
        max_dd_duration=max_dd_dur,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        volatility=volatility,
        n_points=n,
        years=years,
    )


# ── 场景函数（对应 index.ts）─────────────────────────────────────────────────


def grade_performance(perf: dict[str, Any]) -> GradeResult:
    """评级单标的回测（完整绩效字典，6 维度，不含收益率维度）。

    Args:
        perf: ``PerformanceAnalyzer.compute()`` 产出的绩效字典（键同
            ``total_return`` / ``sharpe`` / ``max_drawdown`` / ``win_rate`` /
            ``profit_factor`` / ``calmar`` / ``volatility`` / ``total_trades``）。
    """
    dimensions = [
        score_dimension("calmar", perf.get("calmar", 0.0), 0.18),
        score_dimension("max_drawdown", perf.get("max_drawdown", 0.0), 0.17),
        score_dimension("win_rate", perf.get("win_rate", 0.0), 0.17),
        score_dimension("profit_factor", perf.get("profit_factor", 0.0), 0.18),
        score_dimension("sharpe", perf.get("sharpe", 0.0), 0.15),
        score_dimension("volatility", perf.get("volatility", 0.0), 0.15),
    ]
    vetoes, insufficient, is_losing = _apply_vetoes(
        profit_factor=_num_opt(perf.get("profit_factor")),
        total_trades=int(perf.get("total_trades") or 0),
        max_drawdown=_num_opt(perf.get("max_drawdown")),
        win_rate=_num_opt(perf.get("win_rate")),
    )
    if insufficient:
        _downweight_unreliable(dimensions)
    return _build_result("single", dimensions, vetoes, insufficient, is_losing)


def grade_grid_point(
    point: dict[str, Any],
    total_trades_override: int | None = None,
) -> GradeResult:
    """评级寻优网格点（4 字段子集，4 维度降级版）。

    Args:
        point: 网格点结果（total_return/sharpe/max_drawdown/total_trades/
            win_rate/profit_factor）。
        total_trades_override: 覆盖交易笔数（排名表统一基准）。
    """
    total_trades = (
        total_trades_override
        if total_trades_override is not None
        else int(point.get("total_trades") or 0)
    )
    dimensions = [
        score_dimension("sharpe", _num_or(point.get("sharpe")), 0.3),
        score_dimension("max_drawdown", _num_or(point.get("max_drawdown"), 1.0), 0.28),
        score_dimension("win_rate", _num_or(point.get("win_rate")), 0.22),
        score_dimension("profit_factor", _num_or(point.get("profit_factor")), 0.2),
    ]
    vetoes, insufficient, is_losing = _apply_vetoes(
        profit_factor=_num_opt(point.get("profit_factor")),
        total_trades=total_trades,
        max_drawdown=_num_opt(point.get("max_drawdown")),
        win_rate=_num_opt(point.get("win_rate")),
    )
    if insufficient:
        _downweight_unreliable(dimensions)
    return _build_result("optimize", dimensions, vetoes, insufficient, is_losing)


def grade_portfolio_equity(equity: list[dict[str, Any]]) -> GradeResult:
    """评级组合回测（净值曲线重算，5 维度）。

    Args:
        equity: 组合净值点列表（combined_equity，含 total / datetime /
            drawdown_pct）。
    """
    m = compute_combined_metrics(equity)
    dimensions = [
        score_dimension("calmar", m.calmar, 0.25),
        score_dimension("max_drawdown", m.max_drawdown, 0.22),
        score_dimension("sharpe", m.sharpe, 0.22),
        score_dimension("sortino", m.sortino, 0.15),
        score_dimension("volatility", m.volatility, 0.16),
    ]
    # 样本充足性：≥60 个净值点视为统计有效（与前端同口径）
    sample_proxy = 30 if m.n_points >= 60 else 5
    vetoes, insufficient, is_losing = _apply_vetoes(
        max_drawdown=m.max_drawdown,
        total_trades=sample_proxy,
    )
    return _build_result("portfolio", dimensions, vetoes, insufficient, is_losing)


def _num_opt(v: Any) -> float | None:
    """安全取数（否决规则用）：None/NaN/非法 → None（规则跳过）。"""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _num_or(v: Any, default: float = 0.0) -> float:
    """安全取数（评分维度用）：None/NaN/非法 → default（前端 ``?? default`` 语义）。"""
    f = _num_opt(v)
    return default if f is None else f
