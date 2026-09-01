"""策略综合评分（0-100 加权，v1.25 新增）。

与 :mod:`easy_tdx.backtest.grading` 的分工：

- **grading（S-D 档位）**：面向「是否适合普通人参与」，**刻意不看收益率**，
  六维风险/交易质量加权 + 一票否决；
- **scoring（0-100 分）**：面向**策略研发迭代与排名**，收益计入权重，
  可选叠加 Walk-Forward 样本外稳定性维度。借鉴 backtest-system 的
  ``score_engine()`` 权重体系：收益 50% + 夏普 15% + 回撤 10% +
  索提诺 5% + WF 一致性 20%。

子项打分复用 :data:`easy_tdx.backtest.grading.THRESHOLDS` 锚点插值，
新增 ``total_return`` 与 ``wf_consistency`` 两组锚点。WF 未提供时权重
自动归一化到其余四项（无 WF 数据不惩罚、也不加分）。

典型用法::

    from easy_tdx.backtest.scoring import score_strategy

    s = score_strategy(result.performance, wf=wf_result)
    print(s.total, s.grade_of_components)  # 87.3 ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from easy_tdx.backtest.grading import THRESHOLDS, Anchor, interpolate

if TYPE_CHECKING:
    from easy_tdx.backtest.walkforward import WalkForwardResult

__all__ = ["StrategyScore", "score_strategy"]

# 子项权重（backtest-system score_engine 体系）
_WEIGHTS = {
    "total_return": 0.50,
    "sharpe": 0.15,
    "max_drawdown": 0.10,
    "sortino": 0.05,
    "wf_consistency": 0.20,
}

# 总收益率锚点（全样本回测口径；1.0 = +100% 满分）
_RETURN_ANCHORS = (
    Anchor(-0.5, 0),
    Anchor(0.0, 10),
    Anchor(0.2, 40),
    Anchor(0.5, 65),
    Anchor(1.0, 82),
    Anchor(2.0, 95),
    Anchor(3.0, 100),
)

# WF 盈利窗占比锚点（0.5 = 半数窗盈利及格线附近）
_WF_ANCHORS = (
    Anchor(0.0, 0),
    Anchor(0.3, 15),
    Anchor(0.5, 40),
    Anchor(0.7, 65),
    Anchor(0.85, 85),
    Anchor(1.0, 100),
)


@dataclass
class StrategyScore:
    """策略综合评分结果。"""

    total: float  # 0-100 加权总分
    components: dict[str, float] = field(default_factory=dict)  # 各子项 0-100
    weights_used: dict[str, float] = field(default_factory=dict)  # 归一化后实际权重
    wf_provided: bool = False  # 是否叠加了 WF 维度

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 1),
            "components": {k: round(v, 1) for k, v in self.components.items()},
            "weights_used": {k: round(v, 4) for k, v in self.weights_used.items()},
            "wf_provided": self.wf_provided,
        }


def score_strategy(
    performance: dict[str, Any],
    wf: WalkForwardResult | None = None,
) -> StrategyScore:
    """计算策略综合评分。

    Args:
        performance: ``PerformanceAnalyzer.compute()`` 绩效字典。
        wf: 可选 :class:`~easy_tdx.backtest.walkforward.WalkForwardResult`
            （提供时叠加 WF 一致性维度，权重 20%）。

    Returns:
        :class:`StrategyScore`，含总分、子项分与实际权重。
    """

    def _f(key: str, default: float = 0.0) -> float:
        v = performance.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    components: dict[str, float] = {
        "total_return": interpolate(_RETURN_ANCHORS, _f("total_return")),
        "sharpe": interpolate(THRESHOLDS["sharpe"][1], _f("sharpe")),
        "max_drawdown": interpolate(THRESHOLDS["max_drawdown"][1], _f("max_drawdown")),
        "sortino": interpolate(THRESHOLDS["sortino"][1], _f("sortino")),
    }
    weights = {k: w for k, w in _WEIGHTS.items() if k != "wf_consistency"}

    if wf is not None and wf.windows:
        components["wf_consistency"] = interpolate(_WF_ANCHORS, wf.consistency)
        weights["wf_consistency"] = _WEIGHTS["wf_consistency"]

    total_weight = sum(weights.values())
    total = (
        sum(components[k] * w for k, w in weights.items()) / total_weight
        if total_weight > 0
        else 0.0
    )
    return StrategyScore(
        total=total,
        components=components,
        weights_used={k: w / total_weight for k, w in weights.items()},
        wf_provided="wf_consistency" in components,
    )
