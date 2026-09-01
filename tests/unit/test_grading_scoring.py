"""评级后端化对拍测试 + 综合评分测试。

对拍基准：``web-ui/src/grading/__tests__`` 中的前端用例口径（移植一致性）。
保证 Python 后端（CLI/REST 输出）与前端 TS 实现结果一致——同绩效输入必须
得到同分数、同档位、同否决。
"""

from __future__ import annotations

import math

import pytest

from easy_tdx.backtest.grading import (
    compute_combined_metrics,
    grade_grid_point,
    grade_performance,
    grade_portfolio_equity,
    interpolate,
    score_to_grade,
)
from easy_tdx.backtest.scoring import score_strategy
from easy_tdx.backtest.walkforward import WalkForwardResult, WalkForwardWindow

# ── 插值基础（对齐前端 engine.ts 用例）──────────────────────────────────────


def test_interpolate_clamps_and_midpoints():
    # 越界取端点
    assert interpolate.__doc__ is not None  # noqa: B018
    from easy_tdx.backtest.grading import THRESHOLDS

    dd = THRESHOLDS["max_drawdown"][1]
    assert interpolate(dd, -1.0) == 100.0
    assert interpolate(dd, 0.9) == 0.0
    # 锚点中点线性插值：0.1(88) ~ 0.15(78) 之间 0.125 → 83
    assert interpolate(dd, 0.125) == pytest.approx(83.0)
    sh = THRESHOLDS["sharpe"][1]
    assert interpolate(sh, 0.529) == pytest.approx(42.0, abs=1.5)
    # NaN → 0
    assert interpolate(dd, float("nan")) == 0.0


def test_score_to_grade_thresholds():
    assert score_to_grade(95) == "S"
    assert score_to_grade(90) == "S"
    assert score_to_grade(89.9) == "A"
    assert score_to_grade(80) == "A"
    assert score_to_grade(70) == "B"
    assert score_to_grade(50) == "C"
    assert score_to_grade(10) == "D"


# ── 单标评级（对齐前端 gradePerformance 语义）───────────────────────────────


def _perf(**kw) -> dict:
    """构造健康策略的绩效字典（默认无否决触发）。"""
    base = {
        "calmar": 1.2,
        "max_drawdown": 0.18,
        "win_rate": 0.52,
        "profit_factor": 1.9,
        "sharpe": 1.3,
        "volatility": 0.22,
        "total_trades": 40,
        "total_return": 0.45,
        "sortino": 1.8,
    }
    base.update(kw)
    return base


def test_grade_healthy_strategy():
    g = grade_performance(_perf())
    assert g.scenario == "single"
    assert not g.vetoes
    assert not g.insufficient_sample
    assert len(g.dimensions) == 6
    # 手工复核加权分（各维度分数由锚点插值而来）
    total = sum(d.score * d.weight for d in g.dimensions) / sum(d.weight for d in g.dimensions)
    assert g.score == pytest.approx(round(total * 10) / 10, abs=0.05)


def test_grade_losing_system_vetoed_to_d():
    """利润因子 < 1 → 直接 D。"""
    g = grade_performance(_perf(profit_factor=0.8))
    assert g.grade == "D"
    assert g.is_losing
    assert any(v.key == "losing_system" for v in g.vetoes)


def test_grade_deep_drawdown_vetoed_to_d():
    """回撤 > 60% → 直接 D（同时触发 > 50% 的 cap B，取更差）。"""
    g = grade_performance(_perf(max_drawdown=0.65, calmar=0.1))
    assert g.grade == "D"
    keys = {v.key for v in g.vetoes}
    assert "deep_drawdown" in keys and "high_drawdown" in keys


def test_grade_high_drawdown_capped_at_b():
    """回撤 ∈ (50%, 60%] → 最高 B。"""
    g = grade_performance(_perf(max_drawdown=0.55, calmar=0.2))
    assert g.grade in ("B", "C", "D")
    assert g.grade != "A" and g.grade != "S"
    assert any(v.key == "high_drawdown" for v in g.vetoes)


def test_grade_low_winrate_capped():
    """胜率 < 25% 且样本充足 → D；25%~30% → 最高 C。"""
    g1 = grade_performance(_perf(win_rate=0.2))
    assert g1.grade == "D"
    g2 = grade_performance(_perf(win_rate=0.27))
    assert g2.grade in ("C", "D")
    assert any(v.key == "low_winrate" for v in g2.vetoes)


def test_grade_insufficient_sample_downweights():
    """交易 < 10 笔 → win_rate/profit_factor 权重归零重分配，不直接否决。"""
    g = grade_performance(_perf(total_trades=5, win_rate=0.1, profit_factor=0.5))
    assert g.insufficient_sample
    # 利润因子 0.5 仍触发 losing_system 否决（否决不看样本量）
    assert g.is_losing
    # 降权后：win_rate / profit_factor 的 weight 为 0
    w = {d.key: d.weight for d in g.dimensions}
    assert w["win_rate"] == 0.0
    assert w["profit_factor"] == 0.0
    assert sum(w.values()) == pytest.approx(1.0)


def test_grade_returns_do_not_count():
    """评级不看收益率：翻倍收益 vs 亏损收益，只要风险/交易质量相同评级一致。"""
    g1 = grade_performance(_perf(total_return=2.0))
    g2 = grade_performance(_perf(total_return=-0.3))
    assert g1.score == pytest.approx(g2.score)
    assert g1.grade == g2.grade


def test_grade_grid_point_degraded():
    """寻优网格点：4 维度，None 字段安全降级（不崩溃）。"""
    g = grade_grid_point(
        {
            "sharpe": 1.5,
            "max_drawdown": -0.2,
            "win_rate": 0.48,
            "profit_factor": 1.7,
            "total_trades": 25,
        }
    )
    assert g.scenario == "optimize"
    assert len(g.dimensions) == 4
    g2 = grade_grid_point(
        {"sharpe": None, "max_drawdown": None, "win_rate": None, "total_trades": 0}
    )
    assert g2.insufficient_sample  # 0 笔 → 样本不足降权


def test_grade_grid_point_trades_override():
    g = grade_grid_point({"sharpe": 1.0, "win_rate": 0.4}, total_trades_override=30)
    assert not g.insufficient_sample


# ── 组合净值指标重算（对齐前端 computeCombinedMetrics）──────────────────────


def _equity(n: int = 120, start: float = 100.0, daily: float = 0.002) -> list[dict]:
    return [
        {
            "datetime": f"2024-01-{(i % 28) + 1:02d}",
            "total": start * (1 + daily) ** i,
        }
        for i in range(n)
    ]


def test_combined_metrics_steady_growth():
    m = compute_combined_metrics(_equity())
    assert m.n_points == 120
    assert m.total_return == pytest.approx((1.002) ** 119 - 1, rel=1e-6)
    assert m.max_drawdown == pytest.approx(0.0, abs=1e-9)  # 单调涨 → 无回撤
    assert m.sharpe > 5  # 极稳增长 → 高夏普
    assert m.calmar == 999.0  # 无回撤正收益 → 封顶


def test_combined_metrics_with_drawdown():
    eq = _equity()
    # 中段砸一个 20% 的坑再收回
    for i in range(50, 70):
        eq[i]["total"] *= 0.8
    m = compute_combined_metrics(eq)
    assert m.max_drawdown >= 0.19
    assert m.max_dd_duration > 0


def test_combined_metrics_insufficient_points():
    m = compute_combined_metrics([{"total": 100.0}])
    assert m.n_points == 1
    assert m.sharpe == 0.0


def test_grade_portfolio_equity_scenarios():
    g = grade_portfolio_equity(_equity(200))
    assert g.scenario == "portfolio"
    assert len(g.dimensions) == 5
    # 净值点不足 60 → insufficient_sample
    g2 = grade_portfolio_equity(_equity(30))
    assert g2.insufficient_sample


# ── 综合评分（scoring）───────────────────────────────────────────────────────


def test_score_strategy_without_wf():
    s = score_strategy(_perf())
    assert not s.wf_provided
    assert "wf_consistency" not in s.components
    # 无 WF 时权重归一化到四项：50/15/10/5 → /0.8
    assert s.weights_used["total_return"] == pytest.approx(0.625)
    assert 0 <= s.total <= 100


def test_score_strategy_with_wf():
    wf = WalkForwardResult(
        n_windows=7,
        warmup_ratio=0.3,
        windows=[
            WalkForwardWindow(
                index=i,
                start="2024-01-01",
                end="2024-03-01",
                bars=60,
                total_return=0.05,
                sharpe=1.0,
                max_drawdown=0.05,
                total_trades=3,
                win_rate=0.5,
            )
            for i in range(7)
        ],
    )
    wf.consistency = 0.857  # 6/7 窗盈利
    s = score_strategy(_perf(), wf=wf)
    assert s.wf_provided
    assert s.weights_used["wf_consistency"] == pytest.approx(0.20)
    # WF 高一致性应提高总分（其余输入相同）
    wf_bad = WalkForwardResult(
        n_windows=7,
        warmup_ratio=0.3,
        windows=[
            WalkForwardWindow(
                index=i,
                start="2024-01-01",
                end="2024-03-01",
                bars=60,
                total_return=0.05,
                sharpe=1.0,
                max_drawdown=0.05,
                total_trades=3,
                win_rate=0.5,
            )
            for i in range(7)
        ],
    )
    wf_bad.consistency = 0.14  # 1/7
    s_bad = score_strategy(_perf(), wf=wf_bad)
    assert s.total > s_bad.total


def test_score_strategy_penalizes_loss():
    s_win = score_strategy(_perf())
    s_lose = score_strategy(_perf(total_return=-0.4, sharpe=-0.5))
    assert s_win.total > s_lose.total


def test_score_strategy_serializable():
    import json

    s = score_strategy(_perf()).to_dict()
    json.dumps(s)  # 不抛即通过
    assert {"total", "components", "weights_used", "wf_provided"} <= set(s)


def test_score_strategy_nan_safe():
    s = score_strategy({"sharpe": float("nan"), "total_return": float("inf")})
    assert math.isfinite(s.total)
