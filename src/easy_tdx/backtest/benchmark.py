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
        "excess_return": 0.18,                             # 策略 - 买入持有
        "alpha": 0.09, "beta": 0.72,                       # v1.28：CAPM 对比
        "information_ratio": 0.85, "tracking_error": 0.12  # v1.28：主动管理指标
      },
      "config": {...}
    }

基准对比的语义：**同区间、同费率、同初始资金**下，「首根 K 线全仓买入、
持有到末根」的买入持有收益。策略连买入持有都跑不赢时，报告的
``excess_return`` 为负——这是一票否决级别的研发信号。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.fitness import FitnessCheck, FitnessEngine, FitnessReport, FitnessSegment
from easy_tdx.backtest.grading import grade_performance, grade_portfolio_equity
from easy_tdx.backtest.scoring import score_strategy
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import to_json_native
from easy_tdx.backtest.walkforward import (
    MultiStrategyWalkForwardEngine,
    PortfolioWalkForwardEngine,
    WalkForwardEngine,
)

if TYPE_CHECKING:
    import numpy.typing as npt

    from easy_tdx.backtest.types import BacktestResult

    NDArray = npt.NDArray[np.float64]
else:
    NDArray = np.ndarray

__all__ = [
    "evaluate_strategy",
    "evaluate_portfolio",
    "evaluate_multi",
    "run_buy_hold_benchmark",
    "compute_benchmark_comparison",
]


class _BuyAndHold(Strategy):
    """买入持有基准：首根 K 线全仓买入，持有到末根。"""

    def init(self) -> None:
        self._bought = False

    def next(self) -> None:
        if not self._bought:
            self.buy()
            self._bought = True


def _run_buy_hold_result(
    df: pd.DataFrame,
    cash: float = 100000.0,
    commission: float = 0.0003,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
    slippage: float = 0.0,
    execution: str = "next_open",
    symbol: str | None = None,
    auto_fees: bool = False,
) -> BacktestResult:
    """买入持有基准完整回测（内部用，返回 BacktestResult 以取资金曲线）。"""
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
    return engine.run(df)


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
    result = _run_buy_hold_result(
        df, cash, commission, min_commission, stamp_tax, slippage, execution, symbol, auto_fees
    )
    keys = (
        "total_return",
        "annual_return",
        "max_drawdown",
        "sharpe",
        "calmar",
        "volatility",
    )
    return dict(to_json_native({k: result.performance.get(k, 0.0) for k in keys}))


def compute_benchmark_comparison(
    strategy_curve: pd.DataFrame,
    benchmark_curve: pd.DataFrame,
    annual_days: int = 252,
) -> dict[str, float]:
    """策略 vs 基准的 CAPM / 主动管理对比指标（v1.28 新增）。

    从两条资金曲线的日收益率序列计算：

    - ``beta``: 协方差/基准方差，策略对基准的敏感度（1 = 与基准同涨跌）
    - ``alpha``: 年化 CAPM α ≈ (策略日均收益 − β×基准日均收益) × 年化天数，
      简化版（无风险利率并入截距），>0 说明剔除基准影响后仍有超额
    - ``information_ratio``: 年化信息比率 = mean(策略−基准)/std(策略−基准)×√N，
      每 1 单位跟踪误差换来多少超额收益
    - ``tracking_error``: 年化跟踪误差 = std(策略−基准)×√N

    两条曲线按 bar 对齐（截取较短长度）；基准方差为 0（曲线恒定）时
    beta/alpha 记 0，IR 在差值恒正且无波动时沿用 999 上限约定。

    Args:
        strategy_curve: 策略资金曲线（含 total 列）
        benchmark_curve: 基准资金曲线（含 total 列）
        annual_days: 年化交易日数

    Returns:
        {alpha, beta, information_ratio, tracking_error}
    """
    s_total = strategy_curve["total"].to_numpy(dtype=np.float64)
    b_total = benchmark_curve["total"].to_numpy(dtype=np.float64)
    n = min(len(s_total), len(b_total))
    if n < 3:
        return {"alpha": 0.0, "beta": 0.0, "information_ratio": 0.0, "tracking_error": 0.0}

    def _daily_ret(total: NDArray) -> NDArray:
        safe_prev = np.where(total[:-1] != 0, total[:-1], np.nan)
        ret = np.diff(total) / safe_prev
        return ret[np.isfinite(ret)]

    s_ret = _daily_ret(s_total[:n])
    b_ret = _daily_ret(b_total[:n])
    m = min(len(s_ret), len(b_ret))
    if m < 2:
        return {"alpha": 0.0, "beta": 0.0, "information_ratio": 0.0, "tracking_error": 0.0}
    s_ret, b_ret = s_ret[:m], b_ret[:m]

    b_var = float(np.var(b_ret))
    if b_var > 1e-18:
        beta = float(np.cov(s_ret, b_ret)[0, 1] / b_var)
        alpha = float((np.mean(s_ret) - beta * np.mean(b_ret)) * annual_days)
    else:
        beta = 0.0
        alpha = float(np.mean(s_ret) * annual_days)

    diff = s_ret - b_ret
    diff_std = float(np.std(diff))
    if diff_std > 1e-12:
        information_ratio = float(np.mean(diff) / diff_std * np.sqrt(annual_days))
    elif np.mean(diff) > 0:
        information_ratio = 999.0
    else:
        information_ratio = 0.0
    tracking_error = diff_std * np.sqrt(annual_days)

    return {
        "alpha": alpha,
        "beta": beta,
        "information_ratio": information_ratio,
        "tracking_error": tracking_error,
    }


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

    # 5. 基准对比（买入持有，同区间同费率）：超额收益 + Alpha/Beta/IR/TE
    bh_result = _run_buy_hold_result(df, **engine_kwargs)
    bh_keys = ("total_return", "annual_return", "max_drawdown", "sharpe", "calmar", "volatility")
    bh = dict(to_json_native({k: bh_result.performance.get(k, 0.0) for k in bh_keys}))
    comparison = compute_benchmark_comparison(bt.equity_curve, bh_result.equity_curve)

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
            **comparison,
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


def evaluate_portfolio(
    strategy: type[Strategy] | Strategy,
    stocks: list[Any],
    total_cash: float = 1_000_000.0,
    commission: float = 0.0003,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
    slippage: float = 0.0,
    execution: str = "next_open",
    chanlun_level: str | None = None,
    auto_fees: bool = False,
    n_windows: int = 7,
    warmup_ratio: float = 0.3,
    context_bars: int = 60,
    split: tuple[float, float, float] = (0.6, 0.2, 0.2),
) -> dict[str, Any]:
    """一条龙组合评估：组合回测 + 组合 WF + 适配性体检 + 综合评分 + 组合评级
    + 等权买入持有基准对比。

    与 :func:`evaluate_strategy`（单标的）同构的报告结构，前端 EvaluatePanel
    可直接复用；差异点：

    - ``performance`` 来自组合引擎（完整 25 项指标，含 SQN/最大连胜连亏）；
    - ``walkforward`` 来自 :class:`~easy_tdx.backtest.walkforward.PortfolioWalkForwardEngine`；
    - ``fitness`` 为**跨标的聚合**：逐标的跑三段体检，检查项按「≥60% 标的
      通过」的多数口径合成，段指标取截面均值——诚实反映组合整体适配性；
    - ``grade`` 用组合净值口径 :func:`~easy_tdx.backtest.grading.grade_portfolio_equity`；
    - ``benchmark`` 为**等权买入持有组合**（每只标的分 1/N 资金首根买入持有
      到末根，同费率同区间），α/β/信息比率/跟踪误差基于两条组合净值曲线。

    Args:
        strategy: 策略类或实例。
        stocks: :class:`~easy_tdx.backtest.portfolio_engine.StockData` 列表。
        其余参数: 透传给组合回测 / 组合 WF / 适配性（同口径费率与执行）。

    Returns:
        完整评估报告字典（结构同 evaluate_strategy，config 记录标的清单）。
    """
    from easy_tdx.backtest.portfolio_engine import PortfolioBacktestEngine

    engine_kwargs: dict[str, Any] = {
        "total_cash": total_cash,
        "commission": commission,
        "min_commission": min_commission,
        "stamp_tax": stamp_tax,
        "slippage": slippage,
        "execution": execution,
        "chanlun_level": chanlun_level,
        "auto_fees": auto_fees,
    }

    # 1. 全样本组合回测（完整 25 项指标 + 合并净值曲线）
    bt = PortfolioBacktestEngine(strategy=strategy, stocks=stocks, **engine_kwargs).run()
    perf = bt.total_performance

    # 2. 组合 Walk-Forward 样本外
    wf = PortfolioWalkForwardEngine(
        strategy=strategy,
        stocks=stocks,
        n_windows=n_windows,
        warmup_ratio=warmup_ratio,
        context_bars=context_bars,
        **engine_kwargs,
    ).run()

    # 3. 适配性体检：逐标的跑三段体检，跨标的多数口径聚合
    fitness_kwargs: dict[str, Any] = {
        k: v for k, v in engine_kwargs.items() if k not in ("total_cash", "chanlun_level")
    }
    per_stock_fitness = [
        FitnessEngine(
            strategy=strategy, split=split, context_bars=context_bars, **fitness_kwargs
        ).evaluate(stock.df)
        for stock in stocks
    ]
    fitness = _aggregate_fitness(per_stock_fitness, split)

    # 4. 综合评分（叠加组合 WF 一致性）+ 组合评级（净值曲线口径）
    score = score_strategy(dict(perf), wf=wf)
    grade = grade_portfolio_equity(bt.combined_equity.to_dict(orient="records"))

    # 5. 基准对比：等权买入持有组合（每只标的 1/N 首根买入持有到末根，同费率）
    bh_bt = PortfolioBacktestEngine(strategy=_BuyAndHold, stocks=stocks, **engine_kwargs).run()
    bh_keys = ("total_return", "annual_return", "max_drawdown", "sharpe", "calmar", "volatility")
    bh = dict(to_json_native({k: bh_bt.total_performance.get(k, 0.0) for k in bh_keys}))
    comparison = compute_benchmark_comparison(bt.combined_equity, bh_bt.combined_equity)

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
            **comparison,
        },
        "config": {
            "stocks": [f"{s.market}{s.code}" for s in stocks],
            "total_cash": total_cash,
            "auto_fees": auto_fees,
            "execution": execution,
            "n_windows": n_windows,
            "warmup_ratio": warmup_ratio,
            "split": list(split),
        },
    }


def _aggregate_fitness(
    reports: list[FitnessReport],
    split: tuple[float, float, float],
    pass_ratio_threshold: float = 0.6,
) -> FitnessReport:
    """把逐标的的适配性体检报告聚合为组合级报告（多数口径）。

    - 检查项：同名检查项跨标的计通过率，≥ ``pass_ratio_threshold``（默认
      60%）标的通过则组合级该项通过，detail 记「x/y 只标的通过」；
    - 段摘要：段起止取各标的的最早/最晚，收益/夏普/胜率取截面均值，
      最大回撤取最深（max），交易数取合计——回答「组合整体在三段的形态」。
    """
    aggregated = FitnessReport(split=split)
    valid = [r for r in reports if r.checks]
    if not valid:
        return aggregated

    # 检查项：按首份报告的检查顺序（FitnessEngine 的 8 项固定顺序）
    n = len(valid)
    for check in valid[0].checks:
        passed_n = sum(1 for r in valid for c in r.checks if c.name == check.name and c.passed)
        aggregated.checks.append(
            FitnessCheck(
                name=check.name,
                passed=passed_n >= max(1, int(np.ceil(pass_ratio_threshold * n))),
                detail=f"{passed_n}/{n} 只标的通过（组合多数口径）",
            )
        )

    # 段摘要：train/valid/test 逐段截面聚合
    for seg in valid[0].segments:
        same = [s for s in (r.segment_by_name(seg.name) for r in valid) if s is not None]
        if not same:
            continue
        aggregated.segments.append(
            FitnessSegment(
                name=seg.name,
                start=min(s.start for s in same),
                end=max(s.end for s in same),
                bars=int(round(float(np.mean([s.bars for s in same])))),
                total_return=float(np.mean([s.total_return for s in same])),
                sharpe=float(np.mean([s.sharpe for s in same])),
                max_drawdown=float(max(s.max_drawdown for s in same)),
                total_trades=int(sum(s.total_trades for s in same)),
                win_rate=float(np.mean([s.win_rate for s in same])),
            )
        )

    aggregated.pass_ratio = (
        sum(1 for c in aggregated.checks if c.passed) / len(aggregated.checks)
        if aggregated.checks
        else 0.0
    )
    aggregated.high_fitness = aggregated.pass_ratio >= 0.75
    return aggregated


def evaluate_multi(
    strategies: list[Any],
    total_cash: float = 1_000_000.0,
    commission: float = 0.0003,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
    slippage: float = 0.0,
    execution: str = "next_open",
    n_windows: int = 7,
    warmup_ratio: float = 0.3,
    context_bars: int = 60,
    split: tuple[float, float, float] = (0.6, 0.2, 0.2),
) -> dict[str, Any]:
    """多策略组合一条龙评估：组合回测 + 组合 WF + 跨槽位适配性体检 + 综合评分
    + 组合评级 + 等权买入持有基准对比。

    与 :func:`evaluate_portfolio`（一个策略 × 多标的）同构，报告结构一致；
    差异点仅在槽位划分——每个槽位是「一个策略 × 它自己的标的」
    （:class:`~easy_tdx.backtest.multi_strategy_engine.StrategySlot`）：

    - 全样本回测走 :class:`~easy_tdx.backtest.multi_strategy_engine.MultiStrategyEngine`；
    - Walk-Forward 走
      :class:`~easy_tdx.backtest.walkforward.MultiStrategyWalkForwardEngine`；
    - 适配性体检逐槽位（各自策略 × 各自标的）跑三段后按多数口径聚合；
    - 买入持有基准 = 各槽位标的的等权买入持有组合（策略换成 _BuyAndHold，
      其余不变），α/β/信息比率/跟踪误差基于两条组合净值曲线。

    Args:
        strategies: StrategySlot 列表（每个槽位已绑定策略实例与 K 线）。
        其余参数: 透传给组合回测 / 组合 WF / 适配性（同口径费率与执行）。

    Returns:
        完整评估报告字典（结构同 evaluate_strategy，config 记录槽位清单）。
    """
    from easy_tdx.backtest.multi_strategy_engine import MultiStrategyEngine, StrategySlot

    engine_kwargs: dict[str, Any] = {
        "total_cash": total_cash,
        "commission": commission,
        "min_commission": min_commission,
        "stamp_tax": stamp_tax,
        "slippage": slippage,
        "execution": execution,
    }

    # 1. 全样本组合回测（完整 25 项指标 + 合并净值曲线）
    bt = MultiStrategyEngine(strategies=list(strategies), **engine_kwargs).run()
    perf = bt.total_performance

    # 2. 组合 Walk-Forward 样本外
    wf = MultiStrategyWalkForwardEngine(
        strategies=list(strategies),
        n_windows=n_windows,
        warmup_ratio=warmup_ratio,
        context_bars=context_bars,
        **engine_kwargs,
    ).run()

    # 3. 适配性体检：逐槽位（各自策略 × 各自标的）跑三段体检，多数口径聚合
    per_cash = total_cash / max(len(strategies), 1)
    fitness_kwargs: dict[str, Any] = {
        "commission": commission,
        "min_commission": min_commission,
        "stamp_tax": stamp_tax,
        "slippage": slippage,
        "execution": execution,
    }
    per_slot_fitness = [
        FitnessEngine(
            strategy=slot.strategy,
            split=split,
            context_bars=context_bars,
            cash=per_cash,
            **fitness_kwargs,
        ).evaluate(slot.df)
        for slot in strategies
    ]
    fitness = _aggregate_fitness(per_slot_fitness, split)

    # 4. 综合评分（叠加组合 WF 一致性）+ 组合评级（净值曲线口径）
    score = score_strategy(dict(perf), wf=wf)
    grade = grade_portfolio_equity(bt.combined_equity.to_dict(orient="records"))

    # 5. 基准对比：各槽位标的的等权买入持有组合（策略换成 _BuyAndHold，其余不变）
    bh_slots = [
        StrategySlot(label=s.label, symbol=s.symbol, strategy=_BuyAndHold(), df=s.df)
        for s in strategies
    ]
    bh_bt = MultiStrategyEngine(strategies=bh_slots, **engine_kwargs).run()
    bh_keys = ("total_return", "annual_return", "max_drawdown", "sharpe", "calmar", "volatility")
    bh = dict(to_json_native({k: bh_bt.total_performance.get(k, 0.0) for k in bh_keys}))
    comparison = compute_benchmark_comparison(bt.combined_equity, bh_bt.combined_equity)

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
            **comparison,
        },
        "config": {
            "slots": [f"{s.label}@{s.symbol}" for s in strategies],
            "total_cash": total_cash,
            "execution": execution,
            "n_windows": n_windows,
            "warmup_ratio": warmup_ratio,
            "split": list(split),
        },
    }
