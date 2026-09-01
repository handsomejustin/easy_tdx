"""Walk-Forward 样本外验证引擎（v1.25 新增）。

回测全样本收益好 ≠ 策略好——参数可能只是拟合了某一段行情。Walk-Forward
把时间轴切成多个连续窗口，逐窗独立回测，检验策略在**不同时段**是否稳定
盈利（时间维度的样本外验证）。

切窗与执行语义（借鉴 backtest-system 踩坑后的严格定义）：

1. **切窗**：前 ``warmup_ratio``（默认 30%）作为初始预热区不参与评估，
   其余样本均分为 ``n_windows``（默认 7）个连续测试窗。
2. **每窗独立开仓**：每个窗口从**空仓**开始、窗口结束强制了结评估——
   持仓不跨窗结转。若把窗口首尾直接拼起来，跨窗持仓会被「期初买入期末
   卖出」重复计收益（backtest-system v1.2.1 修复的经典坑）。
3. **指标预热不污染**：窗口开始前带 ``context_bars``（默认 60）根上下文
   K 线供指标计算，用引擎的 ``warmup_bars`` 压制该区间的信号生成——指标
   有历史、信号只属于窗口内。

聚合口径：

- ``window_returns``：各窗收益率列表（时间升序）；
- ``consistency``：盈利窗占比（0~1，WF 稳定性的核心指标）；
- ``chained_return``：各窗收益连乘（每窗独立、窗口间现金复利的近似）；
- ``worst_window`` / ``best_window``：最差/最好窗收益（尾部风险直觉）。

不做什么：本引擎**不做逐窗重寻参**（经典 anchored/rolling 优化式 WF），
只做「同参数跨时段稳定性」检验——参数寻优由
:class:`~easy_tdx.backtest.optimizer.ParamGridOptimizer` 负责，两者组合
（每窗内寻参、窗外评估）留待后续版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import to_json_native

__all__ = ["WalkForwardWindow", "WalkForwardResult", "WalkForwardEngine"]


@dataclass
class WalkForwardWindow:
    """单个测试窗的独立回测结果。"""

    index: int  # 窗序号（0 起，时间升序）
    start: str  # 窗口首根 K 线日期（YYYY-MM-DD）
    end: str  # 窗口末根 K 线日期
    bars: int  # 窗口 K 线数
    total_return: float
    sharpe: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    performance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(
            to_json_native(
                {
                    "index": self.index,
                    "start": self.start,
                    "end": self.end,
                    "bars": self.bars,
                    "total_return": self.total_return,
                    "sharpe": self.sharpe,
                    "max_drawdown": self.max_drawdown,
                    "total_trades": self.total_trades,
                    "win_rate": self.win_rate,
                    "performance": self.performance,
                }
            )
        )


@dataclass
class WalkForwardResult:
    """Walk-Forward 验证汇总。"""

    n_windows: int
    warmup_ratio: float
    windows: list[WalkForwardWindow] = field(default_factory=list)
    # 聚合指标（windows 为空时为 0/NaN 安全值）
    consistency: float = 0.0  # 盈利窗占比
    chained_return: float = 0.0  # 各窗收益连乘 - 1
    mean_window_return: float = 0.0
    median_window_return: float = 0.0
    worst_window: float = 0.0
    best_window: float = 0.0
    mean_sharpe: float = 0.0
    worst_drawdown: float = 0.0
    total_trades: int = 0

    @property
    def window_returns(self) -> list[float]:
        """各窗收益率（时间升序）。"""
        return [w.total_return for w in self.windows]

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_windows": self.n_windows,
            "warmup_ratio": self.warmup_ratio,
            "windows": [w.to_dict() for w in self.windows],
            "consistency": self.consistency,
            "chained_return": self.chained_return,
            "mean_window_return": self.mean_window_return,
            "median_window_return": self.median_window_return,
            "worst_window": self.worst_window,
            "best_window": self.best_window,
            "mean_sharpe": self.mean_sharpe,
            "worst_drawdown": self.worst_drawdown,
            "total_trades": self.total_trades,
        }


class WalkForwardEngine:
    """Walk-Forward 样本外验证：切窗、逐窗独立回测、聚合稳定性指标。

    Example:
        >>> wf = WalkForwardEngine(strategy=MyStrategy, n_windows=7)
        >>> result = wf.run(df)
        >>> result.consistency  # 盈利窗占比
        0.71
    """

    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        n_windows: int = 7,
        warmup_ratio: float = 0.3,
        context_bars: int = 60,
        cash: float = 100000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        symbol: str | None = None,
        auto_fees: bool = False,
    ) -> None:
        """Initialize.

        Args:
            strategy: 策略类或实例（各窗共用同一策略与参数）。
            n_windows: 测试窗数量（默认 7）。
            warmup_ratio: 初始预热区占比（默认 0.3，不参与评估）。
            context_bars: 每窗前置上下文 K 线数（指标预热，默认 60）。
            cash / commission / min_commission / stamp_tax / slippage /
                execution: 透传给各窗的 :class:`BacktestEngine`。
            symbol / auto_fees: 品种感知费率（同 ``BacktestEngine``）。
        """
        self._strategy = strategy
        self._n_windows = max(int(n_windows), 2)
        self._warmup_ratio = min(max(float(warmup_ratio), 0.0), 0.8)
        self._context_bars = max(int(context_bars), 0)
        self._engine_kwargs: dict[str, Any] = {
            "cash": cash,
            "commission": commission,
            "min_commission": min_commission,
            "stamp_tax": stamp_tax,
            "slippage": slippage,
            "execution": execution,
            "symbol": symbol,
            "auto_fees": auto_fees,
        }

    def run(self, df: pd.DataFrame) -> WalkForwardResult:
        """执行 Walk-Forward 验证。

        Args:
            df: 完整 K 线（datetime/open/high/low/close，时间升序）。

        Returns:
            :class:`WalkForwardResult`。数据不足以切窗时返回空结果
            （``windows`` 为空，聚合指标为 0）。
        """
        result = WalkForwardResult(n_windows=self._n_windows, warmup_ratio=self._warmup_ratio)
        n = len(df)
        # 最少数据：每窗 ≥ 20 根 + 预热区 ≥ 20 根
        min_bars = 20 * (1 + self._n_windows)
        if n < min_bars:
            return result

        eval_start = int(n * self._warmup_ratio)
        eval_len = n - eval_start
        window_len = eval_len // self._n_windows

        for i in range(self._n_windows):
            s = eval_start + i * window_len
            e = s + window_len if i < self._n_windows - 1 else n  # 末窗吃到尾部
            if e - s < 5:
                continue
            win = self._run_window(df, s, e, i)
            if win is not None:
                result.windows.append(win)

        self._aggregate(result)
        return result

    def _run_window(self, df: pd.DataFrame, s: int, e: int, index: int) -> WalkForwardWindow | None:
        """独立回测单个窗口 [s, e)。

        带前置上下文（指标预热），用 warmup_bars 压制上下文区间的信号；
        窗口起点空仓（每窗独立开仓语义）。
        """
        ctx_s = max(0, s - self._context_bars)
        lead = s - ctx_s  # 上下文 bar 数 = 需压制的信号数
        sub = df.iloc[ctx_s:e].reset_index(drop=True)
        if len(sub) < lead + 5:
            return None

        engine = BacktestEngine(
            strategy=self._strategy,
            warmup_bars=lead,
            **self._engine_kwargs,
        )
        try:
            bt = engine.run(sub)
        except Exception:  # noqa: BLE001 — 单窗失败不拖垮整组，跳过该窗
            return None
        perf = bt.performance

        dt = self._dates(sub, lead)
        return WalkForwardWindow(
            index=index,
            start=dt[0],
            end=dt[1],
            bars=int(e - s),
            total_return=float(perf.get("total_return", 0.0)),
            sharpe=float(perf.get("sharpe", 0.0)),
            max_drawdown=float(perf.get("max_drawdown", 0.0)),
            total_trades=int(perf.get("total_trades", 0)),
            win_rate=float(perf.get("win_rate", 0.0)),
            performance={k: v for k, v in perf.items()},
        )

    @staticmethod
    def _dates(sub: pd.DataFrame, lead: int) -> tuple[str, str]:
        """取窗口起止日期（跳过 lead 根上下文）。"""
        col = "datetime" if "datetime" in sub.columns else "date"
        vals = sub[col].iloc[lead:]
        if len(vals) == 0:
            return "", ""
        return (
            pd.Timestamp(vals.iloc[0]).strftime("%Y-%m-%d"),
            pd.Timestamp(vals.iloc[-1]).strftime("%Y-%m-%d"),
        )

    @staticmethod
    def _aggregate(result: WalkForwardResult) -> None:
        """聚合各窗指标（空列表安全）。"""
        ws = result.windows
        if not ws:
            return
        rets = np.array([w.total_return for w in ws], dtype=float)
        result.consistency = float(np.mean(rets > 0))
        result.chained_return = float(np.prod(1.0 + rets) - 1.0)
        result.mean_window_return = float(np.mean(rets))
        result.median_window_return = float(np.median(rets))
        result.worst_window = float(np.min(rets))
        result.best_window = float(np.max(rets))
        result.mean_sharpe = float(np.mean([w.sharpe for w in ws]))
        result.worst_drawdown = float(min(w.max_drawdown for w in ws))
        result.total_trades = int(sum(w.total_trades for w in ws))
