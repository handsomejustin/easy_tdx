"""单元测试：多策略资金分仓组合回测引擎（MultiStrategyEngine）。

覆盖：
- 基本多策略回测（2~3 个策略，各跑各的 df，合并曲线）
- 资金均分（1/N）
- individual_results 的 key 格式 "{label}@{symbol}"
- 合并净值曲线列结构 + 日期并集对齐
- 空策略列表兜底
- 同标的不同策略可区分
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.backtest.multi_strategy_engine import (
    MultiStrategyEngine,
    StrategySlot,
)
from easy_tdx.backtest.strategy import Strategy


class SimpleBuyStrategy(Strategy):
    """简单策略：bar 5 买入，bar 30 卖出。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        if self._bar_index == 5 and self.position["size"] == 0:
            self.buy(size=0)
        elif self._bar_index == 30 and self.position["size"] > 0:
            self.sell(size=0)


class HoldStrategy(Strategy):
    """从不交易的策略（净值曲线恒等于初始资金）。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        pass


def _make_df(n: int = 100, seed: int = 42, start: str = "2024-01-01") -> pd.DataFrame:
    """生成随机 OHLCV DataFrame（与 test_portfolio_engine 同构造方式）。"""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = low + rng.uniform(0, high - low, n)
    vol = rng.integers(1_000_000, 10_000_000, n).astype(float)
    return pd.DataFrame(
        {
            "datetime": pd.date_range(start, periods=n, freq="D"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


class TestMultiStrategyEngine:
    def test_basic_run_two_strategies(self) -> None:
        """两个策略各跑各的 df，应产出合并结果。"""
        slots = [
            StrategySlot("双均线", "SH:601088", SimpleBuyStrategy(), _make_df(100, seed=42)),
            StrategySlot("RSI", "SZ:000001", SimpleBuyStrategy(), _make_df(100, seed=99)),
        ]
        engine = MultiStrategyEngine(slots, total_cash=1_000_000)
        result = engine.run()

        # individual_results 的 key 形如 "{label}@{symbol}"
        assert set(result.individual_results.keys()) == {
            "双均线@SH:601088",
            "RSI@SZ:000001",
        }
        # 整体绩效含基本字段
        assert "total_return" in result.total_performance
        assert result.total_performance["total_stocks"] == 2
        assert result.total_performance["total_cash"] == 1_000_000

    def test_total_performance_has_full_metrics(self) -> None:
        """组合整体绩效应含完整 19 项指标（夏普/回撤/胜率/盈亏比等），与单标的同口径。"""
        slots = [
            StrategySlot("双均线", "SH:601088", SimpleBuyStrategy(), _make_df(100, seed=42)),
            StrategySlot("RSI", "SZ:000001", SimpleBuyStrategy(), _make_df(100, seed=99)),
        ]
        perf = MultiStrategyEngine(slots, total_cash=1_000_000).run().total_performance
        # 关键指标都应在（来自 PerformanceAnalyzer）
        for key in [
            "total_return",
            "annual_return",
            "sharpe",
            "sortino",
            "calmar",
            "max_drawdown",
            "max_dd_duration",
            "volatility",
            "total_trades",
            "win_trades",
            "lose_trades",
            "win_rate",
            "profit_factor",
            "avg_win",
            "avg_loss",
            "max_win",
            "max_loss",
        ]:
            assert key in perf, f"缺少指标 {key}"
        # max_drawdown 用正值约定（与单标的一致），介于 0~1
        assert 0 <= perf["max_drawdown"] <= 1
        # 合并净值曲线的 drawdown 也应是正值
        result = MultiStrategyEngine(slots, total_cash=1_000_000).run()
        assert (result.combined_equity["drawdown"] >= 0).all()

    def test_capital_split_equal(self) -> None:
        """资金按策略数均分：每个槽位 1/N。"""
        slots = [
            StrategySlot("A", "SH:601088", SimpleBuyStrategy(), _make_df(50, seed=1)),
            StrategySlot("B", "SZ:000001", SimpleBuyStrategy(), _make_df(50, seed=2)),
            StrategySlot("C", "SZ:000002", SimpleBuyStrategy(), _make_df(50, seed=3)),
        ]
        engine = MultiStrategyEngine(slots, total_cash=900_000)
        allocs = engine._compute_allocations()  # noqa: SLF001 — 测试内部均分逻辑
        assert len(allocs) == 3
        assert all(v == 300_000 for v in allocs.values())
        # equity_allocation 是占比，各 1/3
        result = engine.run()
        assert all(abs(v - 1 / 3) < 1e-9 for v in result.equity_allocation.values())

    def test_combined_equity_has_expected_columns(self) -> None:
        """合并净值曲线应有 datetime/total/drawdown/drawdown_pct 列。"""
        slots = [
            StrategySlot("A", "SH:601088", SimpleBuyStrategy(), _make_df(60, seed=7)),
        ]
        engine = MultiStrategyEngine(slots, total_cash=500_000)
        result = engine.run()
        cols = set(result.combined_equity.columns)
        assert {"datetime", "total", "drawdown", "drawdown_pct"} <= cols
        assert len(result.combined_equity) > 0

    def test_combined_equity_aligns_disjoint_dates(self) -> None:
        """两个策略日期范围不同时，合并曲线应按并集对齐（ffill）。"""
        # 策略 A 跑 2024-01 起 60 根，策略 B 跑 2024-03 起 60 根
        df_a = _make_df(60, seed=1, start="2024-01-01")
        df_b = _make_df(60, seed=2, start="2024-03-01")
        slots = [
            StrategySlot("A", "SH:601088", SimpleBuyStrategy(), df_a),
            StrategySlot("B", "SZ:000001", SimpleBuyStrategy(), df_b),
        ]
        engine = MultiStrategyEngine(slots, total_cash=1_000_000)
        result = engine.run()
        # 合并曲线长度应至少覆盖两个范围的最晚结束日（并集）
        assert len(result.combined_equity) >= 60

    def test_empty_strategies_returns_empty_result(self) -> None:
        """空策略列表应返回空结果，不抛异常。"""
        engine = MultiStrategyEngine([], total_cash=1_000_000)
        result = engine.run()
        assert result.individual_results == {}
        assert result.total_performance["total_return"] == 0.0
        # combined_equity 为带表头的空 DataFrame
        assert len(result.combined_equity) == 0
        assert set(result.combined_equity.columns) == {
            "datetime",
            "total",
            "drawdown",
            "drawdown_pct",
        }

    def test_same_symbol_different_strategies_distinguished(self) -> None:
        """同标的不同策略应能区分（key 含 label）。"""
        df = _make_df(60, seed=5)
        slots = [
            StrategySlot("双均线", "SH:601088", SimpleBuyStrategy(), df.copy()),
            StrategySlot("RSI", "SH:601088", HoldStrategy(), df.copy()),
        ]
        engine = MultiStrategyEngine(slots, total_cash=1_000_000)
        result = engine.run()
        # 两个 key 不同，都带同一 symbol
        assert "双均线@SH:601088" in result.individual_results
        assert "RSI@SH:601088" in result.individual_results

    def test_hold_strategy_keeps_initial_capital(self) -> None:
        """从不交易的策略，其净值曲线末值应等于初始分得资金。"""
        slots = [
            StrategySlot("Hold", "SH:601088", HoldStrategy(), _make_df(40, seed=1)),
        ]
        engine = MultiStrategyEngine(slots, total_cash=1_000_000)
        result = engine.run()
        ec = result.individual_results["Hold@SH:601088"].equity_curve
        # 不交易 → 末值 ≈ 初始资金 1_000_000（单策略拿全部）
        assert abs(ec["total"].iloc[-1] - 1_000_000) < 1.0

    def test_to_dict_serializable(self) -> None:
        """to_dict 应产出 JSON 兼容结构（含 individual_results / combined_equity）。"""
        slots = [
            StrategySlot("A", "SH:601088", SimpleBuyStrategy(), _make_df(50, seed=1)),
        ]
        result = MultiStrategyEngine(slots, total_cash=500_000).run()
        d = result.to_dict()
        assert "total_performance" in d
        assert "individual_results" in d
        assert "combined_equity" in d
        assert isinstance(d["individual_results"]["A@SH:601088"], dict)
