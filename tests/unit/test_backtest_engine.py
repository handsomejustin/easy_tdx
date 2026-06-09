"""Test BacktestEngine orchestration."""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx import MyTT
from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 1, n)
    low = close - rng.uniform(0, 1, n)
    open_ = low + rng.uniform(0, high - low, n)
    volume = rng.integers(1000000, 10000000, n)

    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


class MACrossStrategy(Strategy):
    """Simple MA crossover strategy."""

    def init(self):
        self.ma5 = self.I(MyTT.MA, self.data.close, 5)
        self.ma20 = self.I(MyTT.MA, self.data.close, 20)
        self.cross_up = False
        self.cross_down = False

    def next(self):
        # Check if crossing happened on this bar
        if self._bar_index > 0:
            prev_ma5 = self.ma5[self._bar_index - 1]
            prev_ma20 = self.ma20[self._bar_index - 1]
            curr_ma5 = self.ma5[self._bar_index]
            curr_ma20 = self.ma20[self._bar_index]

            # Golden cross: ma5 crosses above ma20
            if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                self.buy(size=0)
            # Death cross: ma5 crosses below ma20
            elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                self.sell(size=0)


class FixedBuyStrategy(Strategy):
    """Strategy with fixed buy/sell at specific bars."""

    def init(self):
        pass

    def next(self):
        if self._bar_index == 5:
            self.buy(size=100)
        if self._bar_index == 50:
            self.sell(size=100)


class ChanlunStrategy(Strategy):
    """Strategy that uses chanlun result."""

    def init(self):
        pass

    def next(self):
        if self._bar_index == 10 and hasattr(self, "chanlun"):
            # Access chanlun result
            _ = self.chanlun
            self.buy(size=50)


class PrecomputedIndicatorStrategy(Strategy):
    """Strategy that uses precomputed indicator columns."""

    def init(self):
        # Assume BOLL_UPPER already exists in df
        if hasattr(self.data, "BOLL_UPPER"):
            self.boll_upper = self.data.BOLL_UPPER
        else:
            self.boll_upper = None

    def next(self):
        if self.boll_upper is not None and self._bar_index == 20:
            _ = self.boll_upper[self._bar_index]
            self.buy(size=10)


def test_basic_run():
    """Test basic engine run with MACrossStrategy."""
    df = _make_df(n=200)
    engine = BacktestEngine(MACrossStrategy, cash=100000)
    result = engine.run(df)

    # Check performance metrics
    assert result.performance is not None
    assert "total_return" in result.performance

    # Check equity curve length
    assert len(result.equity_curve) == 200

    # Check columns
    assert "datetime" in result.equity_curve.columns
    assert "total" in result.equity_curve.columns


def test_fixed_strategy():
    """Test FixedBuyStrategy produces trades."""
    df = _make_df(n=100)
    engine = BacktestEngine(FixedBuyStrategy, cash=100000)
    result = engine.run(df)

    # Should have at least 2 trades
    assert len(result.trades) >= 2, f"Expected at least 2 trades, got {len(result.trades)}"

    # Check buy at bar 5
    buy_trades = result.trades[result.trades["direction"] == "BUY"]
    assert len(buy_trades) >= 1, "No buy trades found"

    # Check sell at bar 50
    sell_trades = result.trades[result.trades["direction"] == "SELL"]
    assert len(sell_trades) >= 1, "No sell trades found"


def test_result_columns():
    """Test BacktestResult has correct columns."""
    df = _make_df(n=100)
    engine = BacktestEngine(MACrossStrategy)
    result = engine.run(df)

    # Equity curve columns
    expected_ec_cols = ["datetime", "cash", "position_value", "total"]
    for col in expected_ec_cols:
        assert col in result.equity_curve.columns

    # Trades columns
    expected_trade_cols = ["datetime", "direction", "size", "price", "pnl"]
    for col in expected_trade_cols:
        assert col in result.trades.columns


def test_to_dict():
    """Test BacktestResult is serializable."""
    df = _make_df(n=50)
    engine = BacktestEngine(MACrossStrategy)
    result = engine.run(df)

    # to_dict should not raise
    d = result.to_dict()
    assert "performance" in d
    assert "equity_curve" in d
    assert "trades" in d

    # to_json should not raise
    json_str = result.to_json()
    assert len(json_str) > 0


def test_chanlun_injection():
    """Test chanlun result injection."""
    df = _make_df(n=50)

    # Mock chanlun result
    chanlun_result = {"test": "data"}

    engine = BacktestEngine(ChanlunStrategy)
    result = engine.run(df, chanlun_result=chanlun_result)

    # Should have trades
    assert len(result.trades) >= 1


def test_this_close_warning_in_config():
    """Test future_leak_warning in config when using this_close."""
    df = _make_df(n=50)
    engine = BacktestEngine(MACrossStrategy, execution="this_close")
    result = engine.run(df)

    # Config should have future_leak_warning
    # Note: MACrossStrategy may not generate signals, so warning might be False
    assert "future_leak_warning" in result.config


def test_config_snapshot():
    """Test config contains correct cash and commission."""
    df = _make_df(n=50)
    engine = BacktestEngine(MACrossStrategy, cash=50000, commission=0.0005, execution="next_open")
    result = engine.run(df)

    # Check config
    assert result.config["cash"] == 50000
    assert result.config["commission"] == 0.0005
    assert result.config["execution"] == "next_open"


def test_precomputed_indicator_columns():
    """Test strategy works with precomputed indicator columns."""
    df = _make_df(n=50)
    # Add precomputed BOLL_UPPER column
    df["BOLL_UPPER"] = df["close"] * 1.05

    engine = BacktestEngine(PrecomputedIndicatorStrategy)
    result = engine.run(df)

    # Should not crash and should have trades
    assert len(result.equity_curve) == 50


def test_empty_df():
    """Test engine with empty DataFrame."""
    df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])
    engine = BacktestEngine(MACrossStrategy)
    result = engine.run(df)

    # Should return empty result
    assert len(result.equity_curve) == 0
    assert len(result.trades) == 0


def test_strategy_instance_vs_class():
    """Test engine accepts both strategy class and instance."""
    df = _make_df(n=50)

    # Test with class
    engine1 = BacktestEngine(MACrossStrategy)
    result1 = engine1.run(df)
    assert len(result1.equity_curve) == 50

    # Test with instance
    strat = MACrossStrategy()
    engine2 = BacktestEngine(strat)
    result2 = engine2.run(df)
    assert len(result2.equity_curve) == 50


def test_commission_calculation():
    """Test commission is correctly applied."""
    df = _make_df(n=100)
    engine = BacktestEngine(
        FixedBuyStrategy,
        cash=100000,
        commission=0.001,
        min_commission=10.0,
    )
    result = engine.run(df)

    # Should have trades
    assert len(result.trades) >= 2

    # Check trades have commission
    assert (result.trades["commission"] > 0).all()


def test_pnl_calculation():
    """Test PnL is calculated for sell trades."""
    df = _make_df(n=100, seed=123)  # Use specific seed for predictable prices
    engine = BacktestEngine(FixedBuyStrategy, cash=100000, commission=0.0)
    result = engine.run(df)

    # Should have trades
    assert len(result.trades) >= 2

    # Get trades - should have at least one BUY and one SELL
    buy_trades = result.trades[result.trades["direction"] == "BUY"]
    sell_trades = result.trades[result.trades["direction"] == "SELL"]

    assert len(buy_trades) >= 1
    assert len(sell_trades) >= 1

    # PnL is calculated for sell trades
    # Check that sell trades have PnL computed
    assert (sell_trades["pnl"] != 0).any() or len(sell_trades) == 0

    # For buy trades, PnL should be 0
    assert (buy_trades["pnl"] == 0).all()


class PositionAwareStrategy(Strategy):
    """Strategy that checks position before trading (the common pattern)."""

    def init(self):
        self.ma5 = self.I(MyTT.MA, self.data.close, 5)
        self.ma20 = self.I(MyTT.MA, self.data.close, 20)
        self.cross_up = False
        self.cross_down = False

    def next(self):
        if self._bar_index > 0:
            prev_ma5 = self.ma5[self._bar_index - 1]
            prev_ma20 = self.ma20[self._bar_index - 1]
            curr_ma5 = self.ma5[self._bar_index]
            curr_ma20 = self.ma20[self._bar_index]

            if prev_ma5 <= prev_ma20 and curr_ma5 > curr_ma20:
                if self.position["size"] == 0:
                    self.buy(size=0)
            elif prev_ma5 >= prev_ma20 and curr_ma5 < curr_ma20:
                if self.position["size"] > 0:
                    self.sell(size=0)


def test_position_aware_buy_sell_alternation():
    """Regression: strategy that checks position must produce alternating BUY/SELL."""
    df = _make_df(n=300, seed=42)
    engine = BacktestEngine(PositionAwareStrategy, cash=100000)
    result = engine.run(df)

    trades = result.trades[result.trades["rejected"] == False]
    directions = trades["direction"].tolist()

    # Must have both BUYs and SELLs
    assert "BUY" in directions, "No BUY trades generated"
    assert "SELL" in directions, "No SELL trades generated — position feedback broken"

    # Trades must alternate: no two consecutive BUYs or SELLs
    for i in range(1, len(directions)):
        assert directions[i] != directions[i - 1], (
            f"Consecutive same-direction trades at index {i}: "
            f"{directions[i - 1]} -> {directions[i]}"
        )


def test_position_aware_no_duplicate_buys():
    """After a BUY, position['size'] > 0 so strategy should not buy again."""
    df = _make_df(n=300, seed=42)
    engine = BacktestEngine(PositionAwareStrategy, cash=100000)
    result = engine.run(df)

    buy_trades = result.trades[
        (result.trades["direction"] == "BUY") & (result.trades["rejected"] == False)
    ]

    # Each BUY's size should be reasonable (not tiny leftover from exhausted cash)
    if len(buy_trades) > 1:
        # No consecutive buys where the second is tiny (cash leftover artifact)
        sizes = buy_trades["size"].tolist()
        for i in range(1, len(sizes)):
            # Second buy in a pair should not be tiny compared to first
            # (would indicate position wasn't tracked between bars)
            if i >= 1:
                prev_size = sizes[i - 1]
                cur_size = sizes[i]
                # Allow some variance but not orders-of-magnitude difference
                if prev_size > 0:
                    assert cur_size > prev_size * 0.1, (
                        f"Suspicious tiny buy {cur_size} after {prev_size} — "
                        f"position feedback may be broken"
                    )
