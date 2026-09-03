"""单元测试：多标的组合回测引擎."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.portfolio_engine import (
    PortfolioBacktestEngine,
    StockData,
)
from easy_tdx.backtest.strategy import Strategy


class SimpleBuyStrategy(Strategy):
    """简单策略：bar 5 买入，bar 30 卖出."""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0)
        elif self._bar_index == 30 and self.position["size"] > 0:
            self.sell(size=0)


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """生成随机 OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = low + rng.uniform(0, high - low, n)
    vol = rng.integers(1000000, 10000000, n).astype(float)

    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


class TestPortfolioBacktest:
    """测试组合回测引擎."""

    def test_basic_portfolio_run(self) -> None:
        """基本组合回测应正常完成."""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]

        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert result.total_performance is not None
        assert "total_return" in result.total_performance
        assert len(result.individual_results) == 2
        assert result.total_performance["total_stocks"] == 2

    def test_equal_allocation(self) -> None:
        """均等分配：每只标的资金应为总资金/标的数."""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("000002", "SZ", _make_df(100, seed=99)),
        ]

        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=100000,
            allocation="equal",
        )
        result = engine.run()

        # 每只标的分配 50000
        assert result.equity_allocation["SZ000001"] == 0.5
        assert result.equity_allocation["SZ000002"] == 0.5

    def test_empty_stocks(self) -> None:
        """空标的列表应返回零绩效."""
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=[],
            total_cash=100000,
        )
        result = engine.run()

        assert result.total_performance["total_return"] == 0.0
        assert len(result.individual_results) == 0

    def test_to_dict_serializable(self) -> None:
        """结果应可序列化为字典."""
        stocks = [StockData("000001", "SZ", _make_df(100))]
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=100000,
        )
        result = engine.run()
        d = result.to_dict()

        assert "total_performance" in d
        assert "individual_results" in d
        assert "equity_allocation" in d
        assert "combined_equity" in d


class TestStrategyInstanceParams:
    """测试策略实例（带参数）的透传——Phase 3 引擎改造的核心."""

    def test_strategy_instance_params_passed_through(self) -> None:
        """传策略实例时，参数应透传到每个标的（而非用默认值）."""
        from easy_tdx.backtest.strategies import get_registry

        entry = get_registry().get("ma_cross")
        strategy_instance = entry.build({"fast": 10, "slow": 30})

        stocks = [
            StockData("000001", "SZ", _make_df(120, seed=1)),
            StockData("000002", "SZ", _make_df(120, seed=2)),
        ]
        engine = PortfolioBacktestEngine(
            strategy=strategy_instance,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert len(result.individual_results) == 2
        for res in result.individual_results.values():
            assert res.performance is not None


class TestCombinedEquity:
    """测试组合净值曲线生成."""

    def test_combined_equity_generated(self) -> None:
        """组合净值曲线应生成且含 total/drawdown/drawdown_pct 列."""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert len(result.combined_equity) > 0
        cols = set(result.combined_equity.columns)
        assert {"datetime", "total", "drawdown", "drawdown_pct"} <= cols
        assert result.combined_equity["total"].iloc[0] > 0

    def test_combined_equity_date_alignment(self) -> None:
        """日期范围不同的标的应正确对齐（forward-fill）."""
        stocks = [
            StockData("000001", "SZ", _make_df(80, seed=1)),
            StockData("000002", "SZ", _make_df(100, seed=2)),
        ]
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=stocks,
            total_cash=200000,
        )
        result = engine.run()

        assert len(result.combined_equity) >= 100

    def test_combined_equity_empty(self) -> None:
        """空标的列表应返回空净值曲线（带表头）."""
        engine = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy,
            stocks=[],
            total_cash=100000,
        )
        result = engine.run()

        assert len(result.combined_equity) == 0
        assert set(result.combined_equity.columns) == {
            "datetime",
            "total",
            "drawdown",
            "drawdown_pct",
        }


class TestPortfolioFullMetrics:
    """v1.31：组合级完整绩效指标（合并净值 + 汇总成交喂 PerformanceAnalyzer）。"""

    def test_total_performance_has_full_metrics(self) -> None:
        """组合整体绩效应含与单标的同口径的完整指标（SQN/连胜连亏等）。"""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]
        result = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy, stocks=stocks, total_cash=200000
        ).run()

        perf = result.total_performance
        # 单标的 PerformanceAnalyzer 的全部关键键 + 组合字段
        for key in (
            "total_return",
            "annual_return",
            "max_drawdown",
            "sharpe",
            "sortino",
            "calmar",
            "volatility",
            "win_rate",
            "profit_factor",
            "sqn",
            "max_consecutive_wins",
            "max_consecutive_losses",
            "total_stocks",
            "total_cash",
        ):
            assert key in perf, f"缺少指标 {key}"
        assert perf["total_stocks"] == 2
        assert perf["total_cash"] == 200000

    def test_annual_return_is_annualized(self) -> None:
        """年化收益应基于时间长度换算，不再等于总收益（旧版直接赋值的简化）。"""
        stocks = [StockData("000001", "SZ", _make_df(400, seed=42))]
        result = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy, stocks=stocks, total_cash=100000
        ).run()
        perf = result.total_performance
        assert perf["annual_return"] != perf["total_return"]

    def test_drawdown_pct_positive_and_relative_to_peak(self) -> None:
        """drawdown/drawdown_pct 应为正值且相对逐点峰值（与单标的/多策略口径一致）。"""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=7)),
        ]
        result = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy, stocks=stocks, total_cash=200000
        ).run()
        ce = result.combined_equity
        assert (ce["drawdown_pct"] >= 0).all()
        assert (ce["drawdown"] >= 0).all()
        # 回撤比例 = 回撤额 / 当时峰值
        peak = ce["total"].cummax()
        expected = (peak - ce["total"]) / peak.where(peak != 0, 1.0)
        np.testing.assert_allclose(ce["drawdown_pct"], expected, rtol=1e-9)

    def test_combined_trades_have_symbol_column(self) -> None:
        """组合层汇总成交应附 symbol 列（FIFO 按标的分组 + 前端明细表用）。"""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]
        result = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy, stocks=stocks, total_cash=200000
        ).run()
        assert "symbol" in result.trades.columns
        assert set(result.trades["symbol"]) == {"SZ000001", "SH600000"}
        # 每个标的的成交数 == 该标的独立回测的成交数
        for key, res in result.individual_results.items():
            n = (result.trades["symbol"] == key).sum()
            assert n == len(res.trades)

    def test_total_return_matches_capital_weighted(self) -> None:
        """组合 total_return 应等于各标的资金加权收益（合并曲线首值=总资金）。"""
        stocks = [
            StockData("000001", "SZ", _make_df(100, seed=42)),
            StockData("600000", "SH", _make_df(100, seed=99)),
        ]
        result = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy, stocks=stocks, total_cash=200000
        ).run()
        weighted = sum(
            0.5 * res.performance.get("total_return", 0.0)
            for res in result.individual_results.values()
        )
        assert result.total_performance["total_return"] == pytest.approx(weighted, abs=1e-9)

    def test_to_dict_contains_trades(self) -> None:
        """to_dict 应包含组合层成交表（REST/AI 解读消费）。"""
        stocks = [StockData("000001", "SZ", _make_df(100, seed=42))]
        result = PortfolioBacktestEngine(
            strategy=SimpleBuyStrategy, stocks=stocks, total_cash=100000
        ).run()
        d = result.to_dict()
        assert "trades" in d
        assert isinstance(d["trades"], list)
