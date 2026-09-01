"""通达信公式 → 回测引擎适配器（v1.27 新增）。

把 :mod:`easy_tdx.formula` 的信号列注入 K 线，再用轻量策略在逐 bar 循环
里读取信号——公式用户零 Python 即可回测（三通道口径一致：CLI
``easy-tdx formula backtest``、REST ``/formula/backtest/run/async``、
Python API :func:`run_formula_backtest`）。

信号约定（与 indicator-lab 一致的语义）：

- 公式的**命名布尔输出**即信号列。默认买入列 = 第一个信号列（或名字含
  「买」/``B`` 的信号列），默认卖出列 = 第二个信号列（或名字含「卖」/
  ``S`` 的信号列），也可显式指定；
- 信号在**下一根 K 线开盘**成交（与引擎 ``next_open`` 默认一致，无未来
  数据）；预热期 NaN 视为无信号。
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.formula import CompiledFormula, FormulaResult, compile_formula

__all__ = [
    "ColumnSignalStrategy",
    "FormulaStrategyError",
    "attach_formula_columns",
    "run_formula_backtest",
]

# 名称提示只认「买/卖」与多字母 BUY/SELL——单字母 A/B/S 是常见中间变量名，
# 按词边界匹配会误判，故不做单字母提示
_BUY_HINT = re.compile(r"买|buy", re.IGNORECASE)
_SELL_HINT = re.compile(r"卖|sell", re.IGNORECASE)


class FormulaStrategyError(ValueError):
    """公式回测配置错误（无可用信号列等）。"""


def attach_formula_columns(
    df: pd.DataFrame,
    compiled: CompiledFormula,
) -> tuple[pd.DataFrame, FormulaResult]:
    """把公式的全部输出列注入 df（副本），返回 (新 df, 公式结果)。"""
    result = compiled.compute(df)
    if not result.columns:
        raise FormulaStrategyError("公式没有命名输出（用 `名称: 表达式;` 声明输出）")
    out = df.copy()
    for name, arr in result.columns.items():
        out[name] = arr
    return out, result


class ColumnSignalStrategy(Strategy):
    """按已注入的信号列交易：买入列=1 全仓买，卖出列=1 全仓卖。"""

    def __init__(self, buy_col: str, sell_col: str | None = None) -> None:
        super().__init__()
        self._buy_col = buy_col
        self._sell_col = sell_col
        self._holding = False

    def init(self) -> None:
        self._holding = False

    def next(self) -> None:
        buy_v = getattr(self.data, self._buy_col)[0]
        buy_on = buy_v == buy_v and buy_v >= 1.0  # NaN 安全
        if buy_on and not self._holding:
            self.buy()
            self._holding = True
            return
        if self._holding and self._sell_col is not None:
            sell_v = getattr(self.data, self._sell_col)[0]
            if sell_v == sell_v and sell_v >= 1.0:
                self.sell()
                self._holding = False


def pick_signal_columns(
    result: FormulaResult,
    buy_col: str | None = None,
    sell_col: str | None = None,
) -> tuple[str, str | None]:
    """解析买/卖信号列：显式指定优先，否则按声明顺序 + 名称提示自动挑选。"""
    signals = result.signals
    if not signals:
        raise FormulaStrategyError(
            f"公式没有布尔信号输出（现有数值输出: {result.values}）；"
            "信号需为比较/逻辑表达式，如 `买入: CROSS(MA(C,5), MA(C,20));`"
        )
    if buy_col is not None:
        if buy_col not in result.columns:
            raise FormulaStrategyError(f"指定的买入列 {buy_col!r} 不在公式输出中")
    else:
        hinted = [s for s in signals if _BUY_HINT.search(s)]
        buy_col = hinted[0] if hinted else signals[0]
    if sell_col is not None:
        if sell_col not in result.columns:
            raise FormulaStrategyError(f"指定的卖出列 {sell_col!r} 不在公式输出中")
    else:
        hinted = [s for s in signals if _SELL_HINT.search(s) and s != buy_col]
        rest = [s for s in signals if s != buy_col]
        sell_col = hinted[0] if hinted else (rest[0] if rest else None)
    return buy_col, sell_col


def _clean_json(obj: Any) -> Any:
    """递归清洗 numpy 标量/Timestamp/NaN → JSON 原生（REST 任务可序列化）。"""
    import numpy as _np

    if isinstance(obj, dict):
        return {str(k): _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean_json(v) for v in obj]
    if isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, _np.floating):
        f = float(obj)
        return f if _np.isfinite(f) else None
    if isinstance(obj, _np.bool_):
        return bool(obj)
    if obj is None or isinstance(obj, str | int | bool):
        return obj
    if isinstance(obj, float):
        return float(obj) if _np.isfinite(obj) else None
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def run_formula_backtest(
    df: pd.DataFrame,
    formula_text: str | CompiledFormula,
    buy_col: str | None = None,
    sell_col: str | None = None,
    cash: float = 100000.0,
    commission: float = 0.0003,
    min_commission: float = 5.0,
    stamp_tax: float = 0.001,
    slippage: float = 0.0,
    execution: str = "next_open",
    symbol: str | None = None,
    auto_fees: bool = False,
) -> dict[str, Any]:
    """公式一条龙回测：注入信号列 → 挑买/卖列 → 引擎回测 → 附公式元信息。

    Returns:
        ``{"performance", "trades", "equity_curve", "config", "grade", "score",
        "formula": {"signals", "values", "buy_col", "sell_col"}}``
    """
    from easy_tdx.backtest.grading import grade_performance
    from easy_tdx.backtest.scoring import score_strategy

    compiled = (
        formula_text if isinstance(formula_text, CompiledFormula) else compile_formula(formula_text)
    )
    enriched, result = attach_formula_columns(df, compiled)
    b_col, s_col = pick_signal_columns(result, buy_col, sell_col)

    engine = BacktestEngine(
        strategy=ColumnSignalStrategy(buy_col=b_col, sell_col=s_col),
        cash=cash,
        commission=commission,
        min_commission=min_commission,
        stamp_tax=stamp_tax,
        slippage=slippage,
        execution=execution,
        symbol=symbol,
        auto_fees=auto_fees,
    )
    bt = engine.run(enriched)
    out: dict[str, Any] = dict(_clean_json(bt.to_dict()))
    out["grade"] = grade_performance(dict(bt.performance)).to_dict()
    out["score"] = score_strategy(dict(bt.performance)).to_dict()
    out["formula"] = {
        "signals": result.signals,
        "values": result.values,
        "buy_col": b_col,
        "sell_col": s_col,
    }
    return out
