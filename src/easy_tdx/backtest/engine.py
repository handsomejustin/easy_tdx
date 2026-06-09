"""BacktestEngine — orchestrate vectorized execution pipeline.

Coordinates Strategy → OrderSimulator → PortfolioTracker → PerformanceAnalyzer.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.performance import PerformanceAnalyzer
from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import BacktestResult, Signal, Trade


class BacktestEngine:
    """Orchestrate backtest execution pipeline.

    Pipeline:
        1. Signal generation (Strategy)
        2. Order simulation (OrderSimulator)
        3. Portfolio tracking (PortfolioTracker)
        4. Performance analysis (PerformanceAnalyzer)

    Example:
        >>> engine = BacktestEngine(MyStrategy, cash=100000)
        >>> result = engine.run(df)
    """

    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        cash: float = 100000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        position_mode: str = "full",
        reject_policy: str = "reduce",
        benchmark: pd.DataFrame | None = None,
    ):
        """Initialize engine.

        Args:
            strategy: Strategy class or instance
            cash: Initial cash
            commission: Commission rate (e.g., 0.0003 = 0.03%)
            min_commission: Minimum commission per trade
            stamp_tax: Stamp tax rate (for sells)
            slippage: Slippage rate
            execution: Execution mode ('next_open', 'this_close')
            position_mode: Position mode ('full', 'long_only', 'short_only')
            reject_policy: Reject policy ('reduce', 'reject')
            benchmark: Benchmark data for performance comparison
        """
        self._strategy_cls = strategy if isinstance(strategy, type) else type(strategy)
        self._strategy_instance = strategy if isinstance(strategy, Strategy) else None

        self._cash = cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution
        self._position_mode = position_mode
        self._reject_policy = reject_policy
        self._benchmark = benchmark

    def run(self, df: pd.DataFrame, chanlun_result: Any | None = None) -> BacktestResult:
        """Run backtest.

        Args:
            df: Price data with OHLCV columns
            chanlun_result: Optional chanlun analysis result for strategy

        Returns:
            BacktestResult with performance, equity_curve, trades, positions, config
        """
        if len(df) == 0:
            return self._empty_result()

        # Step 1: Signal generation
        signals = self._generate_signals(df, chanlun_result)

        # Step 2: Order simulation
        simulator = OrderSimulator(
            df,
            execution=self._execution,
            position_mode=self._position_mode,
            reject_policy=self._reject_policy,
            commission=self._commission,
            min_commission=self._min_commission,
            stamp_tax=self._stamp_tax,
            slippage=self._slippage,
        )
        trades = simulator.simulate(
            signals=signals,
            cash=self._cash,
            position=0.0,
        )

        # Step 3: Portfolio tracking
        trades = self._compute_pnls(trades)
        tracker = PortfolioTracker(df, initial_cash=self._cash)
        tracker.apply_trades(trades)

        # Step 4: Performance analysis
        trades_df = self._trades_to_df(trades)
        performance = PerformanceAnalyzer(
            tracker.equity_curve,
            trades_df,
            risk_free_rate=0.03,
        ).compute()

        # Config snapshot
        config = {
            "cash": self._cash,
            "commission": self._commission,
            "execution": self._execution,
            "position_mode": self._position_mode,
            "reject_policy": self._reject_policy,
            "future_leak_warning": simulator.future_leak_warning,
        }

        return BacktestResult(
            performance=performance,
            equity_curve=tracker.equity_curve,
            trades=trades_df,
            positions=tracker.positions,
            config=config,
        )

    def _generate_signals(self, df: pd.DataFrame, chanlun_result: Any | None) -> list[Signal]:
        """Generate signals from strategy.

        After each bar's signals, update strategy's internal position state so
        subsequent bars can make informed decisions (e.g., "don't buy if already
        holding"). Uses close price as estimate; actual execution price is
        determined later by OrderSimulator.

        Args:
            df: Price data
            chanlun_result: Optional chanlun analysis result

        Returns:
            List of signals
        """
        # Instantiate strategy if needed
        strat = (
            self._strategy_instance if self._strategy_instance is not None else self._strategy_cls()
        )

        # Bind data
        strat._bind_data(df)

        # Inject chanlun result if provided
        if chanlun_result is not None:
            strat._chanlun_result = chanlun_result

        # Initialize position tracking
        strat._cash = self._cash
        strat._position_size = 0.0
        close_arr = df["close"].to_numpy()

        # Call init
        strat._call_init()

        # Generate signals bar by bar
        all_signals: list[Signal] = []
        for i in range(len(df)):
            strat._set_bar_index(i)
            strat._call_next()
            bar_signals = strat._clear_signals()

            # Update strategy position state so next bar sees current holdings
            self._update_strategy_position(strat, bar_signals, close_arr[i])

            all_signals.extend(bar_signals)

        return all_signals

    def _update_strategy_position(
        self, strat: Strategy, signals: list[Signal], est_price: float
    ) -> None:
        """Update strategy's internal position estimate after each bar.

        Uses close price as estimate for full-position calculations.
        The actual execution price is determined by OrderSimulator later.

        Args:
            strat: Strategy instance
            signals: Signals generated on this bar
            est_price: Estimated price (close of current bar)
        """
        for sig in signals:
            price = sig.price or est_price
            if sig.direction == "BUY":
                if sig.size == 0:
                    # Full position: estimate shares (100-lot rounding)
                    shares = int(strat._cash / (price * (1 + self._commission)) / 100) * 100
                    if shares > 0:
                        strat._position_size += shares
                        strat._cash -= shares * price
                else:
                    strat._position_size += sig.size
                    strat._cash -= sig.size * price
            elif sig.direction == "SELL":
                if sig.size == 0:
                    # Full sell
                    strat._cash += strat._position_size * price
                    strat._position_size = 0.0
                else:
                    strat._cash += sig.size * price
                    strat._position_size = max(0.0, strat._position_size - sig.size)

    def _compute_pnls(self, trades: list[Trade]) -> list[Trade]:
        """Compute realized PnL for sell trades.

        Args:
            trades: List of trades

        Returns:
            Trades with PnL computed
        """
        position_cost = 0.0
        position_size = 0.0

        for trade in trades:
            if not trade.rejected:
                if trade.direction == "BUY":
                    position_cost += trade.size * trade.price + trade.commission
                    position_size += trade.size
                    trade.pnl = 0.0
                elif trade.direction == "SELL":
                    if position_size > 0:
                        avg_cost = position_cost / position_size
                        trade.pnl = (trade.price - avg_cost) * trade.size - trade.commission
                        position_cost -= avg_cost * trade.size
                        position_size -= trade.size
                    else:
                        trade.pnl = 0.0

        return trades

    def _trades_to_df(self, trades: list[Trade]) -> pd.DataFrame:
        """Convert trades to DataFrame.

        Args:
            trades: List of trades

        Returns:
            DataFrame with trade data
        """
        if not trades:
            return pd.DataFrame(
                columns=[
                    "datetime",
                    "direction",
                    "size",
                    "price",
                    "commission",
                    "pnl",
                    "rejected",
                ]
            )

        data = [
            {
                "datetime": t.datetime,
                "direction": t.direction,
                "size": t.size,
                "price": t.price,
                "commission": t.commission,
                "pnl": t.pnl,
                "rejected": t.rejected,
            }
            for t in trades
        ]
        return pd.DataFrame(data)

    def _empty_result(self) -> BacktestResult:
        """Return empty result for empty input.

        Returns:
            BacktestResult with empty DataFrames
        """
        perf = PerformanceAnalyzer(
            pd.DataFrame(columns=["total", "drawdown"]),
            pd.DataFrame(columns=["direction", "pnl", "rejected"]),
        ).compute()

        return BacktestResult(
            performance=perf,
            equity_curve=pd.DataFrame(
                columns=["datetime", "cash", "position_value", "total", "drawdown", "drawdown_pct"]
            ),
            trades=pd.DataFrame(
                columns=[
                    "datetime",
                    "direction",
                    "size",
                    "price",
                    "commission",
                    "pnl",
                    "rejected",
                ]
            ),
            positions=pd.DataFrame(
                columns=["datetime", "size", "avg_price", "market_value", "unrealized_pnl"]
            ),
            config={},
        )
