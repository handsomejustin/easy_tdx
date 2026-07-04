"""多策略组合回测引擎（资金分仓 / 并行制）。

与 :class:`~easy_tdx.backtest.portfolio_engine.PortfolioBacktestEngine` 的区别：
- 后者是「**一个**策略 × **多只**股票」，资金按股票均分。
- 本引擎是「**多个**策略 × **各自**原标的」，资金按策略均分，每个策略独立回测，
  各自的净值曲线按日期对齐后求和，得到组合整体净值曲线。

典型场景：用户在策略库勾选若干「好策略」，各跑在它保存时的标的上，看综合表现。

用法::

    engine = MultiStrategyEngine(
        strategies=[
            StrategySlot(label="双均线交叉", symbol="SH:601088", strategy=strat_a, df=df_a),
            StrategySlot(label="RSI反转",     symbol="SZ:000001", strategy=strat_b, df=df_b),
        ],
        total_cash=1_000_000,
    )
    result = engine.run()
    print(result.total_performance)

输出结构与 :class:`~easy_tdx.backtest.portfolio_engine.PortfolioResult` 一致，便于
前端复用组合页的净值曲线 / 对比表 / 叠加图组件。``individual_results`` 的 key 形如
``"双均线交叉@SH:601088"``（既能区分同标的不同策略，又一眼看清跑哪个票）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import BacktestResult


@dataclass
class StrategySlot:
    """单个策略槽位：一个已构造的策略实例 + 它要跑的标的标识与 K 线。

    Attributes:
        label: 策略展示名（如 "双均线交叉"），用于拼 individual_results 的 key。
        symbol: 标的完整代码（如 "SH:601088"），仅用于标识与展示。
        strategy: 已构造（带参数）的策略实例。
        df: 该标的的 K 线 DataFrame。
    """

    label: str
    symbol: str
    strategy: Strategy
    df: pd.DataFrame


@dataclass
class MultiStrategyResult:
    """多策略组合回测结果（字段语义与 PortfolioResult 对齐，便于前端复用）。

    Attributes:
        total_performance: 组合整体绩效（资金加权收益率 + 策略数 + 总资金）。
        individual_results: 每个策略槽位的独立回测结果，key 形如 "{label}@{symbol}"。
        equity_allocation: 每个槽位的资金分配比例（均分时各 1/N）。
        combined_equity: 组合整体净值曲线（各槽位按日期并集 ffill 对齐后求和），
            列: datetime / total / drawdown / drawdown_pct。
    """

    total_performance: dict[str, float]
    individual_results: dict[str, BacktestResult]
    equity_allocation: dict[str, float]
    combined_equity: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_performance": self.total_performance,
            "individual_results": {k: v.to_dict() for k, v in self.individual_results.items()},
            "equity_allocation": self.equity_allocation,
            "combined_equity": self.combined_equity.to_dict(orient="records"),
        }


class MultiStrategyEngine:
    """多策略资金分仓组合回测引擎。

    把总资金按策略数均分，每个策略在各自的 K 线上独立回测（各跑各的），
    再把各净值曲线按日期对齐求和，得到组合整体净值。资金分配方式固定为
    "equal"（均分）——多策略组合的目标是"看综合表现"，均分是最直接的基线。

    参数与 :class:`~easy_tdx.backtest.portfolio_engine.PortfolioBacktestEngine`
    对齐（``strategy``/``stocks`` 换成 ``strategies``），便于复用资金/成本配置。
    """

    def __init__(
        self,
        strategies: list[StrategySlot],
        total_cash: float = 1_000_000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
    ) -> None:
        self._strategies = strategies
        self._total_cash = total_cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution

    def _compute_allocations(self) -> dict[str, float]:
        """资金均分：每个策略槽位拿 total_cash / N。"""
        n = len(self._strategies)
        if n == 0:
            return {}
        per = self._total_cash / n
        return {self._key(s): per for s in self._strategies}

    @staticmethod
    def _key(s: StrategySlot) -> str:
        """individual_results / allocation 的统一 key："{label}@{symbol}"。"""
        return f"{s.label}@{s.symbol}"

    def run(self) -> MultiStrategyResult:
        """逐策略独立回测，再汇总成组合整体绩效与合并净值曲线。"""
        allocations = self._compute_allocations()
        individual_results: dict[str, BacktestResult] = {}

        for slot in self._strategies:
            key = self._key(slot)
            cash = allocations.get(key, 0)
            engine = BacktestEngine(
                strategy=slot.strategy,
                cash=cash,
                commission=self._commission,
                min_commission=self._min_commission,
                stamp_tax=self._stamp_tax,
                slippage=self._slippage,
                execution=self._execution,
            )
            individual_results[key] = engine.run(slot.df)

        total_alloc = sum(allocations.values())
        equity_pct = {k: v / total_alloc if total_alloc > 0 else 0 for k, v in allocations.items()}
        combined_equity = self._build_combined_equity(individual_results, allocations)
        total_perf = self._aggregate_performance(individual_results, allocations, combined_equity)

        return MultiStrategyResult(
            total_performance=total_perf,
            individual_results=individual_results,
            equity_allocation=equity_pct,
            combined_equity=combined_equity,
        )

    def _aggregate_performance(
        self,
        results: dict[str, BacktestResult],
        allocations: dict[str, float],
        combined_equity: pd.DataFrame,
    ) -> dict[str, float]:
        """组合整体绩效：基于合并净值曲线 + 汇总成交算完整 19 项指标。

        与 PortfolioBacktestEngine 仅给 4 个字段不同，这里把合并净值曲线和所有
        槽位的成交汇总，喂给 PerformanceAnalyzer，得到与单标的回测同口径的完整
        指标（夏普/回撤/胜率/盈亏比等），便于前端复用 MetricTable 展示。
        """
        from easy_tdx.backtest.performance import PerformanceAnalyzer

        total_cash = sum(allocations.values())
        base: dict[str, float] = {
            "total_stocks": float(len(results)),  # 字段名沿用 PortfolioResult
            "total_cash": total_cash,
        }
        if not results or len(combined_equity) < 2:
            base.update({"total_return": 0.0, "annual_return": 0.0})
            return base

        # 汇总所有槽位的成交（concat 成一张表，PerformanceAnalyzer 据此算
        # 胜率/盈亏比/平均盈亏等交易类指标）。所有策略均无成交时给空表兜底。
        trade_frames = [r.trades for r in results.values() if len(r.trades) > 0]
        all_trades = (
            pd.concat(trade_frames, ignore_index=True)
            if trade_frames
            else pd.DataFrame(columns=["direction", "pnl", "rejected"])
        )

        analyzer = PerformanceAnalyzer(equity_curve=combined_equity, trades=all_trades)
        metrics = analyzer.compute()
        metrics["total_stocks"] = float(len(results))
        metrics["total_cash"] = total_cash
        return metrics

    def _build_combined_equity(
        self,
        results: dict[str, BacktestResult],
        allocations: dict[str, float],
    ) -> pd.DataFrame:
        """把各策略独立净值曲线按日期并集 ffill 对齐后求和。

        算法与 ``PortfolioBacktestEngine._build_combined_equity`` 一致：
        各策略回测日期范围可能不同（取数差异、停牌），取 datetime 并集，
        每个策略的 total 列 forward-fill 对齐到并集后求和得组合总净值，
        再算回撤。
        """
        del allocations  # 资金分配不参与曲线形状（各策略独立 full cash 回测，
        # 合并的是 normalized 的净值贡献；保持签名与 Portfolio 版一致便于对照）
        empty = pd.DataFrame(columns=["datetime", "total", "drawdown", "drawdown_pct"])
        if not results:
            return empty

        series_list: list[pd.Series] = []
        for key, result in results.items():
            ec = result.equity_curve
            if len(ec) == 0:
                continue
            dt = ec["datetime"]
            if dt.dtype.kind in "iu":  # int YYYYMMDD
                dt = pd.to_datetime(dt.astype(str), format="%Y%m%d")
            elif dt.dtype != "datetime64[ns]":
                dt = pd.to_datetime(dt)
            s = pd.Series(ec["total"].to_numpy(), index=dt, name=key)
            series_list.append(s)

        if not series_list:
            return empty

        aligned = pd.concat(series_list, axis=1).sort_index()
        aligned = aligned.ffill().fillna(0)
        total = aligned.sum(axis=1)

        # 回撤：drawdown 为绝对回撤额（峰值-当前，正值），drawdown_pct 为相对当时
        # 峰值的回撤比例（drawdown / peak，0~1）。分母必须用逐点 peak 而非固定初始值：
        # 净值大涨后 peak 是初始值的好几倍，若除以 initial 会把回撤百分比严重放大
        # （如峰值 6.45x 初始时，45% 的真实回撤会被算成 293%）。与单标的
        # PortfolioTracker.equity_curve 的 drawdown/drawdown_pct 定义保持一致，
        # PerformanceAnalyzer 直接读 drawdown_pct 列算 max_drawdown。
        peak = total.cummax()
        drawdown = peak - total
        peak_safe = peak.where(peak != 0, 1.0)
        drawdown_pct = drawdown / peak_safe

        return pd.DataFrame(
            {
                "datetime": total.index,
                "total": total.to_numpy(),
                "drawdown": drawdown.to_numpy(),
                "drawdown_pct": drawdown_pct.to_numpy(),
            }
        ).reset_index(drop=True)
