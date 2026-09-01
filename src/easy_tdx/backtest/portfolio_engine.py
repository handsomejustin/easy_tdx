"""多标的组合回测引擎。

支持同时回测多只股票，共享资金池，按策略信号分配资金。
每只标的独立产生信号，引擎统一管理仓位和资金。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import BacktestResult


@dataclass
class StockData:
    """单只标的的数据和标识。

    Attributes:
        code: 股票代码（如 "000001"）
        market: 市场（如 "SZ"）
        df: K线 DataFrame
    """

    code: str
    market: str
    df: pd.DataFrame


@dataclass
class PortfolioResult:
    """组合回测结果。

    Attributes:
        total_performance: 组合整体绩效指标
        individual_results: 每只标的的独立回测结果
        equity_allocation: 每只标的的资金分配比例
        combined_equity: 组合整体净值曲线（按日期对齐各标的求和），
            列: datetime/total/drawdown/drawdown_pct。各标的独立回测日期范围
            可能不同，此处按日期并集 forward-fill 对齐后求和。
    """

    total_performance: dict[str, float]
    individual_results: dict[str, BacktestResult]
    equity_allocation: dict[str, float]
    combined_equity: pd.DataFrame

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化字典。"""
        return {
            "total_performance": self.total_performance,
            "individual_results": {k: v.to_dict() for k, v in self.individual_results.items()},
            "equity_allocation": self.equity_allocation,
            "combined_equity": self.combined_equity.to_dict(orient="records"),
        }


class PortfolioBacktestEngine:
    """多标的组合回测引擎。

    管理多只股票的共享资金池，独立运行策略，
    按均等或自定义比例分配资金。

    用法::

        engine = PortfolioBacktestEngine(
            strategy=MyStrategy,
            stocks=[
                StockData("000001", "SZ", df1),
                StockData("600000", "SH", df2),
            ],
            total_cash=200000,
        )
        result = engine.run()
        print(result.total_performance)
    """

    def __init__(
        self,
        strategy: Strategy | type[Strategy],
        stocks: list[StockData],
        total_cash: float = 200_000.0,
        allocation: str = "equal",
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        chanlun_level: str | None = None,
        auto_fees: bool = False,
    ) -> None:
        """初始化组合回测引擎。

        Args:
            strategy: 策略类或已构造的策略实例。传实例时（如带参数的
                ParametrizedStrategy），参数会被透传到每个标的的回测。
                传类时（CLI 用法）用默认参数。
            stocks: 标的列表（StockData）
            total_cash: 总资金
            allocation: 资金分配方式（目前仅 "equal" 均等分配）
            commission: 佣金率
            min_commission: 最低佣金
            stamp_tax: 印花税
            slippage: 滑点
            execution: 执行模式
            chanlun_level: 缠论级别（可选）
            auto_fees: 为 True 时按各标的代码解析品种费率（ETF/债券免
                印花税等），覆盖默认值；显式非默认费率仍优先。

        .. versionadded:: 1.24
            ``auto_fees`` 品种感知费率（按 StockData.market+code 逐标的解析）。
        """
        self._strategy = strategy
        self._stocks = stocks
        self._total_cash = total_cash
        self._allocation = allocation
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution
        self._chanlun_level = chanlun_level
        self._auto_fees = auto_fees

    def _compute_allocations(self) -> dict[str, float]:
        """计算每只标的的资金分配。"""
        n = len(self._stocks)
        if n == 0:
            return {}

        if self._allocation == "equal":
            per_stock_cash = self._total_cash / n
            return {f"{s.market}{s.code}": per_stock_cash for s in self._stocks}

        # 默认均等分配
        per_stock_cash = self._total_cash / n
        return {f"{s.market}{s.code}": per_stock_cash for s in self._stocks}

    def run(self) -> PortfolioResult:
        """运行组合回测。

        对每只标的独立运行回测，按分配的资金量计算收益，
        最终汇总为组合整体绩效。

        Returns:
            PortfolioResult 包含整体绩效和各标的详细结果
        """
        allocations = self._compute_allocations()
        individual_results: dict[str, BacktestResult] = {}

        for stock in self._stocks:
            key = f"{stock.market}{stock.code}"
            cash = allocations.get(key, 0)

            engine = BacktestEngine(
                strategy=self._strategy,
                cash=cash,
                commission=self._commission,
                min_commission=self._min_commission,
                stamp_tax=self._stamp_tax,
                slippage=self._slippage,
                execution=self._execution,
                chanlun_level=self._chanlun_level,
                symbol=key,
                auto_fees=self._auto_fees,
            )
            result = engine.run(stock.df)
            individual_results[key] = result

        # 汇总整体绩效
        total_perf = self._aggregate_performance(individual_results, allocations)

        # 计算资金占比
        total_alloc = sum(allocations.values())
        equity_pct = {k: v / total_alloc if total_alloc > 0 else 0 for k, v in allocations.items()}

        # 生成组合整体净值曲线（各标的按日期对齐求和）
        combined_equity = self._build_combined_equity(individual_results, allocations)

        return PortfolioResult(
            total_performance=total_perf,
            individual_results=individual_results,
            equity_allocation=equity_pct,
            combined_equity=combined_equity,
        )

    def _aggregate_performance(
        self,
        results: dict[str, BacktestResult],
        allocations: dict[str, float],
    ) -> dict[str, float]:
        """汇总所有标的的绩效为组合整体绩效。

        使用资金加权方式计算组合收益率。

        Args:
            results: 各标的回测结果
            allocations: 各标的资金分配

        Returns:
            组合整体绩效指标
        """
        total_cash = sum(allocations.values())
        if total_cash == 0:
            return {"total_return": 0.0, "annual_return": 0.0}

        # 资金加权收益率
        weighted_return = 0.0
        for key, result in results.items():
            alloc = allocations.get(key, 0)
            weight = alloc / total_cash
            ret = result.performance.get("total_return", 0.0)
            weighted_return += weight * ret

        return {
            "total_return": weighted_return,
            "annual_return": weighted_return,  # 简化，实际应根据周期年化
            "total_stocks": len(results),
            "total_cash": total_cash,
        }

    def _build_combined_equity(
        self,
        results: dict[str, BacktestResult],
        allocations: dict[str, float],
    ) -> pd.DataFrame:
        """把各标的独立净值曲线按日期对齐求和，生成组合整体净值曲线。

        各标的独立回测的日期范围可能不同（取数差异、停牌等），这里取所有标的
        datetime 的并集，每个标的的 total 列 forward-fill 对齐到并集后求和。

        Returns:
            DataFrame: datetime / total / drawdown / drawdown_pct。
            空结果时返回带表头的空 DataFrame。
        """
        empty = pd.DataFrame(columns=["datetime", "total", "drawdown", "drawdown_pct"])
        if not results:
            return empty

        # 收集各标的的 (datetime, total) 系列，以 datetime 为索引
        series_list: list[pd.Series] = []
        for key, result in results.items():
            ec = result.equity_curve
            if len(ec) == 0:
                continue
            # datetime 列可能是 int(YYYYMMDD) 或 datetime；统一转可比字符串/时间戳
            dt = ec["datetime"]
            if dt.dtype.kind in "iu":  # int YYYYMMDD
                dt = pd.to_datetime(dt.astype(str), format="%Y%m%d")
            elif dt.dtype != "datetime64[ns]":
                dt = pd.to_datetime(dt)
            s = pd.Series(ec["total"].to_numpy(), index=dt, name=key)
            series_list.append(s)

        if not series_list:
            return empty

        # 外连接对齐（并集日期），forward-fill 各标的在缺失日期的净值（持有不动），
        # 再求和得组合总净值。缺失值填 0 是为应对某标的完全无该日期数据的情况。
        aligned = pd.concat(series_list, axis=1).sort_index()
        aligned = aligned.ffill().fillna(0)
        total = aligned.sum(axis=1)

        # 计算回撤
        peak = total.cummax()
        drawdown = total - peak
        # drawdown_pct：以初始总资金为基准（peak 的首个值），避免除零
        initial = peak.iloc[0] if len(peak) > 0 and peak.iloc[0] != 0 else 1.0
        drawdown_pct = drawdown / initial

        return pd.DataFrame(
            {
                "datetime": total.index,
                "total": total.to_numpy(),
                "drawdown": drawdown.to_numpy(),
                "drawdown_pct": drawdown_pct.to_numpy(),
            }
        ).reset_index(drop=True)
