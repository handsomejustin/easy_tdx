"""适配性评估（fitness）+ 一条龙评估（benchmark）测试。"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.benchmark import evaluate_strategy, run_buy_hold_benchmark
from easy_tdx.backtest.fitness import FitnessEngine, rolling_fitness_scores
from easy_tdx.backtest.strategy import Strategy


class _BuyFirstBar(Strategy):
    def init(self) -> None:
        self._bought = False

    def next(self) -> None:
        if not self._bought:
            self.buy()
            self._bought = True


class _CycleTrader(Strategy):
    """每 10 根切换一次持仓（买卖交替），保证各段有完整回合（total_trades>0）。"""

    def init(self) -> None:
        self._count = 0
        self._holding = False

    def next(self) -> None:
        self._count += 1
        if self._count % 10 == 0:
            if self._holding:
                self.sell()
                self._holding = False
            else:
                self.buy()
                self._holding = True


def _df(n: int = 500, drift: float = 0.004) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    dates = pd.date_range("2018-01-01", periods=n, freq="B")
    close = 10.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.006, n))
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "vol": 1000.0,
        }
    )


# ── FitnessEngine ─────────────────────────────────────────────────────────────


def test_fitness_three_segments_and_checks():
    rep = FitnessEngine(_CycleTrader).evaluate(_df(600))
    assert [s.name for s in rep.segments] == ["train", "valid", "test"]
    assert len(rep.checks) == 8
    names = {c.name for c in rep.checks}
    assert names == {
        "train_profitable",
        "valid_profitable",
        "test_profitable",
        "sign_consistent",
        "drawdown_bounded",
        "train_enough_trades",
        "test_active",
        "oos_sharpe_positive",
    }
    # 上涨行情 + 买入持有 → 大部分检查通过 → 高适配
    assert rep.pass_ratio >= 0.75
    assert rep.high_fitness


def test_fitness_checks_carry_values():
    rep = FitnessEngine(_CycleTrader).evaluate(_df(600))
    for c in rep.checks:
        assert c.detail  # 每条检查附实际值（可解释性）
        assert isinstance(c.passed, bool)


def test_fitness_losing_market_fails():
    rep = FitnessEngine(_BuyFirstBar).evaluate(_df(600, drift=-0.002))
    assert rep.pass_ratio < 0.75
    assert not rep.high_fitness
    # 三段全亏 → sign_consistent 通过（同号），但盈利检查全挂
    by_name = {c.name: c.passed for c in rep.checks}
    assert by_name["train_profitable"] is False
    assert by_name["valid_profitable"] is False
    assert by_name["test_profitable"] is False


def test_fitness_insufficient_data_returns_empty():
    rep = FitnessEngine(_BuyFirstBar).evaluate(_df(60))  # valid 段 = 12 根 < 20 → 空报告
    assert rep.segments == []
    assert rep.checks == []
    assert rep.high_fitness is False


def test_fitness_invalid_split_raises():
    with pytest.raises(ValueError, match="split"):
        FitnessEngine(_BuyFirstBar, split=(0.5, 0.2, 0.2))


def test_fitness_prefix_no_lookahead():
    """evaluate_prefix 只用前缀：末段测试段终点必须早于 end_index。"""
    df = _df(600)
    rep = FitnessEngine(_BuyFirstBar).evaluate_prefix(df, 400)
    assert [s.name for s in rep.segments] == ["train", "valid", "test"]
    # 前缀评估的测试段末日期 < 第 400 根的日期
    dt_col = "datetime"
    cutoff = pd.Timestamp(df[dt_col].iloc[399]).strftime("%Y-%m-%d")
    assert rep.segments[-1].end <= cutoff


def test_rolling_fitness_scores_series():
    df = _df(700)
    scores = rolling_fitness_scores(df, _BuyFirstBar, step=100, min_prefix=300)
    assert len(scores) >= 3
    assert all(s["index"] < 700 for s in scores)
    assert all(0.0 <= s["pass_ratio"] <= 1.0 for s in scores)
    # 时间升序
    idxs = [s["index"] for s in scores]
    assert idxs == sorted(idxs)


def test_fitness_report_serializable():
    rep = FitnessEngine(_BuyFirstBar).evaluate(_df(500))
    d = rep.to_dict()
    json.dumps(d, default=str)
    assert d["total_checks"] == 8
    assert "high_fitness" in d


# ── benchmark（一条龙评估）────────────────────────────────────────────────────


def test_buy_hold_benchmark_matches_trend():
    df = _df(300, drift=0.002)
    bh = run_buy_hold_benchmark(df)
    total = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    assert bh["total_return"] == pytest.approx(total, rel=0.05)  # 扣少量费用


def test_evaluate_strategy_full_report_structure():
    report = evaluate_strategy(_BuyFirstBar, _df(500))
    for key in (
        "performance",
        "score",
        "grade",
        "walkforward",
        "fitness",
        "benchmark",
        "config",
    ):
        assert key in report
    # 绩效 19 项
    assert "total_return" in report["performance"]
    assert "sharpe" in report["performance"]
    # 评分/评级结构
    assert 0 <= report["score"]["total"] <= 100
    assert report["grade"]["grade"] in ("S", "A", "B", "C", "D")
    # WF
    assert report["walkforward"]["n_windows"] == 7
    # 适配性
    assert report["fitness"]["total_checks"] == 8
    # 基准
    assert "buy_hold" in report["benchmark"]
    assert "excess_return" in report["benchmark"]


def test_evaluate_strategy_excess_return_sign():
    """上涨行情 + 买入持有策略 ≈ 基准本身，excess_return 接近 0（扣费差异）。"""
    report = evaluate_strategy(_BuyFirstBar, _df(400))
    excess = report["benchmark"]["excess_return"]
    assert abs(excess) < 0.05


def test_evaluate_strategy_serializable():
    report = evaluate_strategy(_BuyFirstBar, _df(300), n_windows=3)
    text = json.dumps(report, default=str)
    assert "excess_return" in text


def test_evaluate_strategy_auto_fees_for_etf():
    report = evaluate_strategy(_BuyFirstBar, _df(300), symbol="SH:510300", auto_fees=True)
    assert report["config"]["symbol"] == "SH:510300"
    assert report["config"]["auto_fees"] is True


# ── evaluate_portfolio（v1.31 组合级一条龙）───────────────────────────────────
def _stocks_for_portfolio() -> list[Any]:
    from easy_tdx.backtest.portfolio_engine import StockData

    return [
        StockData("000001", "SZ", _df(400, drift=0.002)),
        StockData("600000", "SH", _df(400, drift=0.003)),
    ]


def test_evaluate_portfolio_full_report_structure():
    """组合一条龙报告与单标的 evaluate_strategy 同构（前端面板可复用）。"""
    from easy_tdx.backtest.benchmark import evaluate_portfolio

    report = evaluate_portfolio(_CycleTrader(), _stocks_for_portfolio(), total_cash=500_000)
    for key in ("performance", "score", "grade", "walkforward", "fitness", "benchmark", "config"):
        assert key in report
    # 组合绩效：完整指标 + 组合字段
    assert "sqn" in report["performance"]
    assert "max_consecutive_losses" in report["performance"]
    assert report["performance"]["total_stocks"] == 2
    # 评分/评级
    assert 0 <= report["score"]["total"] <= 100
    assert report["score"]["wf_provided"] is True
    assert report["grade"]["grade"] in ("S", "A", "B", "C", "D")
    assert report["grade"]["scenario"] == "portfolio"
    # 组合 WF
    assert len(report["walkforward"]["windows"]) > 0
    # 适配性（跨标的聚合）
    assert report["fitness"]["total_checks"] == 8
    assert "只标的通过" in report["fitness"]["checks"][0]["detail"]
    # 基准
    assert "buy_hold" in report["benchmark"]
    assert "excess_return" in report["benchmark"]
    # config 记录标的清单
    assert report["config"]["stocks"] == ["SZ000001", "SH600000"]


def test_evaluate_portfolio_buy_hold_excess_near_zero():
    """首根买入持有策略 ≈ 等权买入持有基准，excess_return 接近 0（扣费差异）。"""
    from easy_tdx.backtest.benchmark import evaluate_portfolio

    report = evaluate_portfolio(_BuyFirstBar(), _stocks_for_portfolio(), total_cash=500_000)
    assert abs(report["benchmark"]["excess_return"]) < 0.05


def test_evaluate_portfolio_serializable():
    from easy_tdx.backtest.benchmark import evaluate_portfolio

    report = evaluate_portfolio(
        _CycleTrader(), _stocks_for_portfolio(), total_cash=500_000, n_windows=3
    )
    text = json.dumps(report, default=str)
    assert "excess_return" in text
