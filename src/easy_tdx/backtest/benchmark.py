"""一条龙策略评估（evaluate_strategy，v1.25 新增）。

把「全样本回测 + Walk-Forward 样本外 + 适配性体检 + 综合评分 + S-D 评级 +
基准对比（买入持有）」打包成一次调用、一份报告（借鉴 backtest-system 的
``evaluate_engine()``「拉数 / 对齐 / 选模式 / 对比参考引擎」一条龙思路，
落在 easy-tdx 的三通道输出上）。

报告结构（全部 JSON 兼容，直接喂 REST / CLI / AI Agent）::

    {
      "performance": {...19 项绩效...},
      "score": {"total": 78.3, "components": {...}},      # 综合评分（含 WF）
      "grade": {"grade": "B", "score": 71.2, ...},         # S-D 评级（不看收益）
      "walkforward": {"consistency": 0.71, "windows": [...]},
      "fitness": {"pass_ratio": 0.875, "high_fitness": true, "checks": [...]},
      "benchmark": {
        "buy_hold": {"total_return": 0.32, ...},
        "excess_return": 0.18                               # 策略 - 买入持有
      },
      "config": {...}
    }

基准对比的语义：**同区间、同费率、同初始资金**下，「首根 K 线全仓买入、
持有到末根」的买入持有收益。策略连买入持有都跑不赢时，报告的
``excess_return`` 为负——这是一票否决级别的研发信号。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.fitness import FitnessEngine
from easy_tdx.backtest.grading import grade_performance
from easy_tdx.backtest.scoring import score_strategy
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import to_json_native
from easy_tdx.backtest.walkforward import WalkForwardEngine

__all__ = ["evaluate_strategy", "run_buy_hold_benchmark"]


class _BuyAndHold(Strategy):
    """买入持有基准：首根 K 线全仓买入，持有到末根。"""

    def init(self) -> None:
        self._bought = False

    def next(self) -> None:
        if not self._bought:
            self.buy()
            self._bought = True


def run_buy_hold_benchmark(
    df: pd.DataFrame,
    cash: float = 100000.0,
    commission: float = 0.0003,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
    slippage: float = 0.0,
    execution: str = "next_open",
    symbol: str | None = None,
    auto_fees: bool = False,
) -> dict[str, Any]:
    """买入持有基准回测（与策略回测同区间、同费率、同资金）。"""
    engine = BacktestEngine(
        strategy=_BuyAndHold,
        cash=cash,
        commission=commission,
        min_commission=min_commission,
        stamp_tax=stamp_tax,
        slippage=slippage,
        execution=execution,
        symbol=symbol,
        auto_fees=auto_fees,
    )
    result = engine.run(df)
    keys = (
        "total_return",
        "annual_return",
        "max_drawdown",
        "sharpe",
        "calmar",
        "volatility",
    )
    return dict(to_json_native({k: result.performance.get(k, 0.0) for k in keys}))


def evaluate_strategy(
    strategy: type[Strategy] | Strategy,
    df: pd.DataFrame,
    cash: float = 100000.0,
    commission: float = 0.0003,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
    slippage: float = 0.0,
    execution: str = "next_open",
    symbol: str | None = None,
    auto_fees: bool = False,
    n_windows: int = 7,
    warmup_ratio: float = 0.3,
    context_bars: int = 60,
    split: tuple[float, float, float] = (0.6, 0.2, 0.2),
) -> dict[str, Any]:
    """一条龙策略评估：回测 + WF + 适配性 + 评分 + 评级 + 基准对比。

    Args:
        strategy: 策略类或实例。
        df: K 线（datetime/open/high/low/close，时间升序）。
        其余参数: 透传给各子引擎（回测 / WF / 适配性共用同口径费率与执行）。
        n_windows / warmup_ratio: Walk-Forward 切窗参数。
        split: 适配性三段占比。

    Returns:
        完整评估报告字典（结构见模块 docstring）。
    """
    engine_kwargs: dict[str, Any] = {
        "cash": cash,
        "commission": commission,
        "min_commission": min_commission,
        "stamp_tax": stamp_tax,
        "slippage": slippage,
        "execution": execution,
        "symbol": symbol,
        "auto_fees": auto_fees,
    }

    # 1. 全样本回测
    bt = BacktestEngine(strategy=strategy, **engine_kwargs).run(df)
    perf = bt.performance

    # 2. Walk-Forward 样本外
    wf = WalkForwardEngine(
        strategy=strategy,
        n_windows=n_windows,
        warmup_ratio=warmup_ratio,
        context_bars=context_bars,
        **engine_kwargs,
    ).run(df)

    # 3. 适配性体检
    fitness = FitnessEngine(
        strategy=strategy,
        split=split,
        context_bars=context_bars,
        **engine_kwargs,
    ).evaluate(df)

    # 4. 综合评分（叠加 WF 一致性）+ S-D 评级
    score = score_strategy(perf, wf=wf)
    grade = grade_performance(perf)

    # 5. 基准对比（买入持有，同区间同费率）
    bh = run_buy_hold_benchmark(df, **engine_kwargs)

    return {
        "performance": to_json_native(dict(perf)),
        "score": score.to_dict(),
        "grade": grade.to_dict(),
        "walkforward": wf.to_dict(),
        "fitness": fitness.to_dict(),
        "benchmark": {
            "buy_hold": bh,
            "excess_return": float(perf.get("total_return", 0.0))
            - float(bh.get("total_return", 0.0)),
        },
        "config": {
            "symbol": symbol,
            "auto_fees": auto_fees,
            "execution": execution,
            "n_windows": n_windows,
            "warmup_ratio": warmup_ratio,
            "split": list(split),
        },
    }
