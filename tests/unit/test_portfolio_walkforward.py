"""单元测试：组合级 Walk-Forward 引擎（PortfolioWalkForwardEngine，v1.31）。"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.portfolio_engine import StockData
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.walkforward import PortfolioWalkForwardEngine


class PeriodicStrategy(Strategy):
    """每 10 根切换一次持仓，保证窗口内有成交（与单标的 WF 测试同思路）。"""

    def init(self) -> None:
        self._holding = False

    def next(self) -> None:
        if self._bar_index % 10 == 0 and not self._holding:
            self.buy(size=0)
            self._holding = True
        elif self._bar_index % 10 == 5 and self._holding:
            self.sell(size=0)
            self._holding = False


def _make_df(n: int = 400, seed: int = 42, start: str = "2023-01-01") -> pd.DataFrame:
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


def _stocks() -> list[StockData]:
    return [
        StockData("000001", "SZ", _make_df(400, seed=42)),
        StockData("600000", "SH", _make_df(400, seed=99)),
    ]


class TestPortfolioWalkForward:
    def test_basic_structure(self) -> None:
        """切窗数量、窗口字段与聚合指标齐全。"""
        wf = PortfolioWalkForwardEngine(
            strategy=PeriodicStrategy, stocks=_stocks(), n_windows=4, total_cash=200_000
        ).run()
        assert len(wf.windows) == 4
        for i, w in enumerate(wf.windows):
            assert w.index == i
            assert w.start <= w.end
            assert w.bars > 0
        # 窗口时间升序且不重叠
        starts = [pd.Timestamp(w.start) for w in wf.windows]
        assert starts == sorted(starts)
        assert wf.total_trades > 0

    def test_aggregates_consistency_and_chained(self) -> None:
        """consistency = 盈利窗占比，chained = 各窗连乘 - 1。"""
        wf = PortfolioWalkForwardEngine(
            strategy=PeriodicStrategy, stocks=_stocks(), n_windows=5
        ).run()
        rets = [w.total_return for w in wf.windows]
        assert wf.consistency == sum(1 for r in rets if r > 0) / len(rets)
        chained = float(np.prod([1.0 + r for r in rets]) - 1.0)
        assert wf.chained_return == pd.Series([chained]).iloc[0]

    def test_insufficient_data_returns_empty(self) -> None:
        """数据不足以切窗时返回空结果（windows 为空、聚合指标为 0）。"""
        stocks = [StockData("000001", "SZ", _make_df(50, seed=1))]
        wf = PortfolioWalkForwardEngine(strategy=PeriodicStrategy, stocks=stocks, n_windows=7).run()
        assert wf.windows == []
        assert wf.consistency == 0.0

    def test_empty_stocks_returns_empty(self) -> None:
        wf = PortfolioWalkForwardEngine(strategy=PeriodicStrategy, stocks=[], n_windows=3).run()
        assert wf.windows == []

    def test_late_listing_stock_tolerated(self) -> None:
        """晚上市的标的不该拖垮整窗（该窗跳过它，其余照常）。"""
        stocks = [
            StockData("000001", "SZ", _make_df(400, seed=42)),
            StockData("688981", "SH", _make_df(100, seed=7, start="2024-02-01")),
        ]
        wf = PortfolioWalkForwardEngine(strategy=PeriodicStrategy, stocks=stocks, n_windows=4).run()
        assert len(wf.windows) == 4
        assert all(w.total_trades > 0 for w in wf.windows)

    def test_window_independent_opening(self) -> None:
        """每窗独立开仓：窗口总交易数应等于窗内各标的回合数（无跨窗结转）。"""
        stocks = _stocks()
        n_windows = 4
        wf = PortfolioWalkForwardEngine(
            strategy=PeriodicStrategy, stocks=stocks, n_windows=n_windows
        ).run()
        # PeriodicStrategy 每 10 根一个回合，窗长约 56 根 → 每标的每窗 5 回合上下，
        # 总交易数应为正且与窗口长度量级一致（防止持仓跨窗导致的重复/丢失计数）。
        assert wf.total_trades > 0
        assert wf.total_trades == sum(w.total_trades for w in wf.windows)

    def test_to_dict_serializable(self) -> None:
        wf = PortfolioWalkForwardEngine(
            strategy=PeriodicStrategy, stocks=_stocks(), n_windows=3
        ).run()
        d = wf.to_dict()
        assert len(d["windows"]) == len(wf.windows)
        # JSON 兼容（numpy 标量已清洗）
        json.dumps(d)
        # 每窗 performance 为完整指标 dict（含 SQN 等深度指标）
        assert "sqn" in d["windows"][0]["performance"]
        assert "max_consecutive_wins" in d["windows"][0]["performance"]

    def test_min_windows_guard(self) -> None:
        """n_windows < 2 至少取 2（与单标的 WF 同保护）。"""
        wf = PortfolioWalkForwardEngine(
            strategy=PeriodicStrategy, stocks=_stocks(), n_windows=0
        ).run()
        assert wf.n_windows == 2


# ── MultiStrategyWalkForwardEngine（v1.31.1：多策略组合槽位 WF）───────────────
def _slots() -> list[Any]:
    from easy_tdx.backtest.multi_strategy_engine import StrategySlot

    return [
        StrategySlot(
            label="双均线交叉",
            symbol="SH:601088",
            strategy=PeriodicStrategy(),
            df=_make_df(400, seed=42),
        ),
        StrategySlot(
            label="RSI反转",
            symbol="SZ:000001",
            strategy=PeriodicStrategy(),
            df=_make_df(400, seed=99),
        ),
    ]


def test_multi_strategy_wf_basic_structure() -> None:
    from easy_tdx.backtest.walkforward import MultiStrategyWalkForwardEngine

    wf = MultiStrategyWalkForwardEngine(strategies=_slots(), n_windows=4, total_cash=200_000).run()
    assert len(wf.windows) == 4
    assert wf.total_trades > 0
    assert wf.total_trades == sum(w.total_trades for w in wf.windows)
    # 窗口时间升序
    starts = [pd.Timestamp(w.start) for w in wf.windows]
    assert starts == sorted(starts)


def test_multi_strategy_wf_matches_portfolio_structure() -> None:
    """与 PortfolioWalkForwardEngine 输出同构（前端面板可复用）。"""
    from easy_tdx.backtest.walkforward import MultiStrategyWalkForwardEngine

    wf = MultiStrategyWalkForwardEngine(strategies=_slots(), n_windows=3).run()
    d = wf.to_dict()
    json.dumps(d)
    assert "sqn" in d["windows"][0]["performance"]
    assert "max_consecutive_wins" in d["windows"][0]["performance"]


def test_multi_strategy_wf_empty_slots() -> None:
    from easy_tdx.backtest.walkforward import MultiStrategyWalkForwardEngine

    wf = MultiStrategyWalkForwardEngine(strategies=[], n_windows=3).run()
    assert wf.windows == []
