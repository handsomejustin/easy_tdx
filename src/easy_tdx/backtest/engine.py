"""BacktestEngine — orchestrate vectorized execution pipeline.

Coordinates Strategy → OrderSimulator → PortfolioTracker → PerformanceAnalyzer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from easy_tdx.backtest.orders import OrderSimulator
from easy_tdx.backtest.performance import PerformanceAnalyzer
from easy_tdx.backtest.portfolio import PortfolioTracker
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import BacktestResult, Signal, Trade

if TYPE_CHECKING:
    from easy_tdx.backtest.execution import ExecutionModel
    from easy_tdx.backtest.slippage import SlippageModel


@dataclass
class _StopCondition:
    """Active stop-loss / take-profit condition tied to an open position.

    Attributes:
        stop_loss: Price below which a SELL is triggered (None = disabled)
        take_profit: Price above which a SELL is triggered (None = disabled)
    """

    stop_loss: float | None
    take_profit: float | None


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
        chanlun_level: str | None = None,
        slippage_model: SlippageModel | None = None,
        execution_model: ExecutionModel | None = None,
        warmup_bars: int = 0,
        symbol: str | None = None,
        auto_fees: bool = False,
        indicator_cache: Any | None = None,
    ):
        """Initialize engine.

        Args:
            strategy: Strategy class or instance
            cash: Initial cash
            commission: Commission rate (e.g., 0.0003 = 0.03%)
            min_commission: Minimum commission per trade
            stamp_tax: Stamp tax rate (for sells)
            slippage: Slippage rate
            execution: Execution mode ('next_open', 'next_close')
            position_mode: Position mode ('full', 'long_only', 'short_only')
            reject_policy: Reject policy ('reduce', 'reject')
            benchmark: Benchmark data for performance comparison
            chanlun_level: Auto-compute chanlun analysis at this level
                (e.g. 'DAILY', '30MIN'). Strategy accesses via self.chanlun.
            slippage_model: Pluggable slippage model (overrides flat slippage
                when provided).
            execution_model: Pluggable execution model (bypasses OrderSimulator
                when provided).
            warmup_bars: 指标预热 bar 数。前 ``warmup_bars`` 根不调用
                ``next()``、不产生信号（指标 NaN 期过滤），避免早期数据不足
                导致的越界或误信号。默认 0（向后兼容）。
            symbol: 标的代码（如 ``"SH:510300"``，供品种感知费率解析）。
            auto_fees: 为 True 且提供 symbol 时，按品种自动解析
                commission/min_commission/stamp_tax（ETF/债券免印花税等），
                覆盖默认值；显式传入的非默认费率仍优先于自动解析。
            indicator_cache: 指标计算缓存（网格寻优跨点复用，见
                :class:`~easy_tdx.backtest.indicator_cache.IndicatorCache`）。
                None = 每次直接计算（默认，向后兼容）。

        .. versionchanged:: 1.24
            新增 ``symbol`` / ``auto_fees`` 品种感知费率参数。
        """
        self._strategy_cls = strategy if isinstance(strategy, type) else type(strategy)
        self._strategy_instance = strategy if isinstance(strategy, Strategy) else None

        self._symbol = symbol
        if auto_fees and symbol:
            from easy_tdx.backtest.fees import resolve_fee_model

            fee = resolve_fee_model(symbol)
            # 显式非默认值优先（调用方有意覆盖），否则用品种默认
            if commission == 0.0003:
                commission = fee.commission
            if min_commission == 5.0:
                min_commission = fee.min_commission
            if stamp_tax == 0.001:
                stamp_tax = fee.stamp_tax

        self._cash = cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution
        self._position_mode = position_mode
        self._reject_policy = reject_policy
        self._benchmark = benchmark
        self._chanlun_level = chanlun_level
        self._slippage_model = slippage_model
        self._execution_model = execution_model
        self._warmup_bars = max(int(warmup_bars), 0)
        self._indicator_cache = indicator_cache

    def run(self, df: pd.DataFrame, chanlun_result: Any | None = None) -> BacktestResult:
        """Run backtest.

        Args:
            df: Price data with OHLCV columns
            chanlun_result: Optional chanlun analysis result for strategy.
                When provided, takes priority over auto-computed result.

        Returns:
            BacktestResult with performance, equity_curve, trades, positions, config
        """
        if len(df) == 0:
            return self._empty_result()

        # 兼容真实行情日线数据：get_security_bars 日线返回 date 列，引擎内部
        # （StrategyDataProxy / PortfolioTracker / _find_bar_index）统一使用
        # datetime 列。缺则由 date 派生，避免上层手动重命名。
        if "datetime" not in df.columns and "date" in df.columns:
            df = df.copy()
            df["datetime"] = df["date"]

        # Auto-compute chanlun if chanlun_level is set and no manual result
        if chanlun_result is None and self._chanlun_level is not None:
            from easy_tdx.chanlun.analyser import ChanlunAnalyser

            analyser = ChanlunAnalyser(frequency=self._chanlun_level)
            chanlun_result = analyser.process_klines(df)

        # Step 1: Signal generation
        signals = self._generate_signals(df, chanlun_result)

        # Step 2: Order simulation
        if self._execution_model is not None:
            # ExecutionModel path
            trades = self._execute_with_model(signals, df)
        else:
            # OrderSimulator path (default)
            simulator = OrderSimulator(
                df,
                execution=self._execution,
                position_mode=self._position_mode,
                reject_policy=self._reject_policy,
                commission=self._commission,
                min_commission=self._min_commission,
                stamp_tax=self._stamp_tax,
                slippage=self._slippage,
                slippage_model=self._slippage_model,
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
        analyzer = PerformanceAnalyzer(
            tracker.equity_curve,
            trades_df,
            risk_free_rate=0.03,
        )
        performance = analyzer.compute()

        # Config snapshot
        config: dict[str, Any] = {
            "cash": self._cash,
            "commission": self._commission,
            "min_commission": self._min_commission,
            "stamp_tax": self._stamp_tax,
            "execution": self._execution,
            "position_mode": self._position_mode,
            "reject_policy": self._reject_policy,
        }
        if self._symbol:
            config["symbol"] = self._symbol

        return BacktestResult(
            performance=performance,
            equity_curve=tracker.equity_curve,
            trades=trades_df,
            positions=tracker.positions,
            config=config,
            diagnostic=analyzer.diagnostic,
        )

    def _execute_with_model(self, signals: list[Signal], df: pd.DataFrame) -> list[Trade]:
        """Use ExecutionModel to process signals."""
        assert self._execution_model is not None
        all_trades: list[Trade] = []
        cash = self._cash
        position = 0.0

        for signal in signals:
            bar_idx = self._find_bar_index(df, signal.datetime)
            if bar_idx is None:
                continue
            sub_trades = self._execution_model.execute(
                signal=signal,
                df=df,
                bar_idx=bar_idx,
                cash=cash,
                position=position,
                position_mode=self._position_mode,
                commission=self._commission,
                min_commission=self._min_commission,
                stamp_tax=self._stamp_tax,
                slippage_model=self._slippage_model,
            )
            for t in sub_trades:
                if not t.rejected:
                    if t.direction == "BUY":
                        cash -= t.size * t.price + t.commission + t.slippage
                        position += t.size
                    else:
                        cash += t.size * t.price - t.commission - t.slippage
                        position -= t.size
            all_trades.extend(sub_trades)
        return all_trades

    @staticmethod
    def _find_bar_index(df: pd.DataFrame, datetime_val: int) -> int | None:
        """Find bar index by datetime value."""
        dt_col = df["datetime"]
        try:
            idx = (dt_col == datetime_val).idxmax() if (dt_col == datetime_val).any() else None
            if idx is not None:
                return int(idx)
        except (TypeError, ValueError):
            pass
        if hasattr(dt_col, "dt"):
            dt_ints = dt_col.dt.strftime("%Y%m%d").astype(int)
            mask = dt_ints == datetime_val
            if mask.any():
                return int(mask.idxmax())
        return None

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
        # 挂载指标缓存（两段式寻优加速；None 时 I() 直接计算）
        strat._indicator_cache = self._indicator_cache

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
        active_stops: list[_StopCondition] = []

        high_arr = df["high"].to_numpy()
        low_arr = df["low"].to_numpy()

        for i in range(len(df)):
            strat._set_bar_index(i)

            # warmup 期（指标 NaN 预热）不调用 next()、不产生信号，但仍推进
            # bar_index 与后续 PortfolioTracker 的资金曲线对齐。
            if i < self._warmup_bars:
                continue

            strat._call_next()
            bar_signals = strat._clear_signals()

            # Check existing SL/TP conditions against current bar's price range
            sl_tp_signals = self._check_stop_conditions(
                active_stops, high_arr[i], low_arr[i], close_arr[i], i, df
            )

            # Combine strategy signals with SL/TP signals
            combined = bar_signals + sl_tp_signals

            # Register new SL/TP from BUY signals (after checking, so they
            # activate on the NEXT bar — consistent with next_open execution)
            for sig in bar_signals:
                if sig.direction == "BUY" and (
                    sig.stop_loss is not None or sig.take_profit is not None
                ):
                    active_stops.append(
                        _StopCondition(stop_loss=sig.stop_loss, take_profit=sig.take_profit)
                    )

            # Clear conditions when a SELL occurs (strategy or SL/TP triggered)
            for sig in combined:
                if sig.direction == "SELL" and active_stops:
                    active_stops.clear()

            # Update strategy position state so next bar sees current holdings
            self._update_strategy_position(strat, combined, close_arr[i])

            all_signals.extend(combined)

        return all_signals

    def _check_stop_conditions(
        self,
        active_stops: list[_StopCondition],
        bar_high: float,
        bar_low: float,
        bar_close: float,
        bar_index: int,
        df: pd.DataFrame,
    ) -> list[Signal]:
        """Check active SL/TP conditions against current bar's price range.

        If triggered, generates a SELL signal at the trigger price and removes
        the condition. Stop-loss is checked first (conservative: assume the
        worst case for the holder).

        Args:
            active_stops: List of active stop conditions
            bar_high: Current bar's high price
            bar_low: Current bar's low price
            bar_close: Current bar's close price
            bar_index: Current bar index
            df: Price DataFrame (for datetime extraction)

        Returns:
            List of SELL signals triggered by SL/TP conditions
        """
        if not active_stops:
            return []

        signals: list[Signal] = []
        remaining: list[_StopCondition] = []

        for cond in active_stops:
            triggered = False
            trigger_price = 0.0

            # Check stop-loss first (worst case for holder)
            if cond.stop_loss is not None and bar_low <= cond.stop_loss:
                triggered = True
                trigger_price = cond.stop_loss
            # Then check take-profit
            elif cond.take_profit is not None and bar_high >= cond.take_profit:
                triggered = True
                trigger_price = cond.take_profit

            if triggered:
                # Get datetime for this bar
                dt_val = df["datetime"].iloc[bar_index]
                if hasattr(dt_val, "strftime"):
                    dt_int = int(dt_val.strftime("%Y%m%d"))
                else:
                    dt_int = int(dt_val)

                signals.append(
                    Signal(
                        datetime=dt_int,
                        direction="SELL",
                        size=0,  # full position close
                        price=trigger_price,
                        source="stop",  # 标记为止损/止盈触发，延迟到下一根成交
                    )
                )
            else:
                remaining.append(cond)

        active_stops.clear()
        active_stops.extend(remaining)
        return signals

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
                        # 记录本次卖出对应的持仓成本基数，用于派生单笔收益率
                        trade.cost_basis = avg_cost * trade.size
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
                    "slippage",
                    "pnl",
                    "cost_basis",
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
                "slippage": t.slippage,
                "pnl": t.pnl,
                "cost_basis": t.cost_basis,
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
        analyzer = PerformanceAnalyzer(
            pd.DataFrame(columns=["total", "drawdown", "drawdown_pct"]),
            pd.DataFrame(columns=["direction", "pnl", "rejected"]),
        )
        perf = analyzer.compute()

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
                    "slippage",
                    "pnl",
                    "rejected",
                ]
            ),
            positions=pd.DataFrame(
                columns=["datetime", "size", "avg_price", "market_value", "unrealized_pnl"]
            ),
            config={},
            diagnostic=analyzer.diagnostic,
        )
