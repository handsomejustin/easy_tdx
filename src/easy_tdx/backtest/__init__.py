"""easy_tdx.backtest — 向量化策略回测引擎（纯计算，零网络依赖）。

快速开始::

    from easy_tdx.backtest import BacktestEngine, Strategy

    class MyStrategy(Strategy):
        def init(self):
            self.ma5 = self.I(MA, self.data.close, 5)
            self.ma20 = self.I(MA, self.data.close, 20)

        def next(self):
            if crossover(self.ma5, self.ma20):
                self.buy()
            elif crossover(self.ma20, self.ma5):
                self.sell()

    engine = BacktestEngine(strategy=MyStrategy, cash=100000)
    result = engine.run(df)
    print(result.performance)
"""

from easy_tdx.backtest.benchmark import evaluate_strategy, run_buy_hold_benchmark  # noqa: F401
from easy_tdx.backtest.combo import CombinationRunner, ComboResult, FactorSignals  # noqa: F401
from easy_tdx.backtest.engine import BacktestEngine  # noqa: F401
from easy_tdx.backtest.fitness import FitnessEngine, FitnessReport  # noqa: F401
from easy_tdx.backtest.formula_strategy import run_formula_backtest  # noqa: F401
from easy_tdx.backtest.grading import GradeResult, grade_performance  # noqa: F401
from easy_tdx.backtest.rotation import RotationEngine, RotationResult  # noqa: F401
from easy_tdx.backtest.scoring import StrategyScore, score_strategy  # noqa: F401
from easy_tdx.backtest.strategy import Strategy, StrategyDataProxy, crossover  # noqa: F401
from easy_tdx.backtest.types import BacktestResult, Position, Signal, Trade  # noqa: F401
from easy_tdx.backtest.walkforward import (  # noqa: F401
    WalkForwardEngine,
    WalkForwardResult,
)

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "CombinationRunner",
    "ComboResult",
    "FactorSignals",
    "FitnessEngine",
    "FitnessReport",
    "GradeResult",
    "Strategy",
    "StrategyDataProxy",
    "StrategyScore",
    "Signal",
    "Trade",
    "Position",
    "WalkForwardEngine",
    "WalkForwardResult",
    "crossover",
    "evaluate_strategy",
    "grade_performance",
    "RotationEngine",
    "RotationResult",
    "run_buy_hold_benchmark",
    "run_formula_backtest",
    "score_strategy",
]
