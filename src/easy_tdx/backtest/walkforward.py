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

__all__ = [
    "WalkForwardWindow",
    "WalkForwardResult",
    "WalkForwardEngine",
    "PortfolioWalkForwardEngine",
]


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


class PortfolioWalkForwardEngine:
    """组合级 Walk-Forward：一个策略 × 多只标的，逐窗独立回测并合成组合净值。

    与 :class:`WalkForwardEngine`（单标的）共用切窗语义与
    :class:`WalkForwardWindow` / :class:`WalkForwardResult` 结构——前端
    WalkForwardPanel 无需改动即可渲染组合 WF：

    1. **参考时间轴**：取全部标的 datetime 的并集（升序），按单标的同样的
       规则切预热区 + ``n_windows`` 个连续测试窗；
    2. **每窗独立开仓**：窗内每只标的带 ``context_bars`` 前置上下文
       （``warmup_bars`` 压制上下文信号），从空仓开始、窗口结束强制了结，
       持仓不跨窗；
    3. **组合净值合成**：各标的窗内净值按等权资金（``total_cash / N``）
       对齐求合成组合窗内净值，再喂 :class:`~easy_tdx.backtest.performance.PerformanceAnalyzer`
       （汇总成交附 symbol 列）得到与单标的同口径的窗指标；
    4. **容错**：某标的数据不足（如晚上市）则该窗跳过该标的；某窗所有
       标的都跑不了则跳过该窗。

    Example:
        >>> wf = PortfolioWalkForwardEngine(strategy=MyStrategy, stocks=stocks, n_windows=7)
        >>> result = wf.run()
        >>> result.consistency  # 组合盈利窗占比
        0.71
    """

    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        stocks: list[Any],
        n_windows: int = 7,
        warmup_ratio: float = 0.3,
        context_bars: int = 60,
        total_cash: float = 1_000_000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        chanlun_level: str | None = None,
        auto_fees: bool = False,
    ) -> None:
        """Initialize.

        Args:
            strategy: 策略类或实例（各窗各标的共用同一策略与参数）。
            stocks: :class:`~easy_tdx.backtest.portfolio_engine.StockData` 列表。
            n_windows / warmup_ratio / context_bars: 切窗参数（同单标的 WF）。
            total_cash: 组合总资金（各标的等权分 1/N）。
            其余参数: 透传给各窗各标的的 :class:`BacktestEngine`。
        """
        self._strategy = strategy
        self._stocks = list(stocks)
        self._n_windows = max(int(n_windows), 2)
        self._warmup_ratio = min(max(float(warmup_ratio), 0.0), 0.8)
        self._context_bars = max(int(context_bars), 0)
        self._total_cash = float(total_cash)
        self._engine_kwargs: dict[str, Any] = {
            "commission": commission,
            "min_commission": min_commission,
            "stamp_tax": stamp_tax,
            "slippage": slippage,
            "execution": execution,
            "chanlun_level": chanlun_level,
            "auto_fees": auto_fees,
        }

    def run(self) -> WalkForwardResult:
        """执行组合 Walk-Forward 验证。

        Returns:
            :class:`WalkForwardResult`。数据不足以切窗时返回空结果
            （``windows`` 为空，聚合指标为 0）。
        """
        result = WalkForwardResult(n_windows=self._n_windows, warmup_ratio=self._warmup_ratio)
        if not self._stocks:
            return result

        # 参考时间轴：全部标的 datetime 的并集（升序）
        timeline = self._reference_timeline()
        n = len(timeline)
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
            win = self._run_window(timeline, s, e, i)
            if win is not None:
                result.windows.append(win)

        WalkForwardEngine._aggregate(result)
        return result

    def _reference_timeline(self) -> pd.DatetimeIndex:
        """全部标的 datetime 的并集（升序，Timestamp 化）。"""
        all_dt: list[pd.Timestamp] = []
        for stock in self._stocks:
            s = self._dt_series(stock.df)
            if len(s) > 0:
                all_dt.append(s)
        if not all_dt:
            return pd.DatetimeIndex([])
        return pd.DatetimeIndex(sorted(pd.unique(pd.concat(all_dt))))

    @staticmethod
    def _dt_series(df: pd.DataFrame) -> pd.Series:
        """标的 K 线的 datetime 列统一转 Timestamp（int YYYYMMDD 兼容）。"""
        col = "datetime" if "datetime" in df.columns else "date"
        dt = df[col]
        if dt.dtype.kind in "iu":
            return pd.to_datetime(dt.astype(str), format="%Y%m%d")
        if not pd.api.types.is_datetime64_any_dtype(dt):
            return pd.to_datetime(dt)
        return pd.Series(pd.to_datetime(dt), index=df.index)

    def _run_window(
        self, timeline: pd.DatetimeIndex, s: int, e: int, index: int
    ) -> WalkForwardWindow | None:
        """独立回测单个窗口 [s, e)（参考时间轴下标），合成组合窗内净值。"""
        window_start = timeline[s]
        window_end = timeline[e - 1]
        ctx_start = timeline[max(0, s - self._context_bars)]

        per_cash = self._total_cash / len(self._stocks)
        equity_series: list[pd.Series] = []
        trade_frames: list[pd.DataFrame] = []
        for stock in self._stocks:
            key = f"{stock.market}{stock.code}"
            dt = self._dt_series(stock.df)
            mask = (dt >= ctx_start) & (dt <= window_end)
            sub = stock.df.loc[mask].reset_index(drop=True)
            dt_sub = dt.loc[mask].reset_index(drop=True)
            # 上下文 bar 数 = 窗口起点之前保留的 bar 数（warmup 压制其信号）
            lead = int((dt_sub < window_start).sum())
            if len(sub) < lead + 5:
                continue  # 该标的数据不足（晚上市/停牌过多），本窗跳过

            engine = BacktestEngine(
                strategy=self._strategy,
                cash=per_cash,
                warmup_bars=lead,
                symbol=key,
                **self._engine_kwargs,
            )
            try:
                bt = engine.run(sub)
            except Exception:  # noqa: BLE001 — 单标的失败不拖垮整窗
                continue

            # 只取窗内净值点（上下文区恒为现金，不参与窗指标，避免稀释波动率）
            ec = bt.equity_curve
            if len(ec) > lead:
                eq = ec.iloc[lead:]
                equity_series.append(
                    pd.Series(eq["total"].to_numpy(), index=self._dt_series(eq), name=key)
                )
            if len(bt.trades) > 0:
                t = bt.trades.copy()
                t["symbol"] = key
                trade_frames.append(t)

        if not equity_series:
            return None  # 所有标的都跑不了，跳过该窗

        # 合成组合窗内净值：日期并集对齐，ffill 持有不动，上市晚于窗口起点的
        # 标的其前导缺口用首值回填（首值即其初始资金——还没开仓，持有现金）
        aligned = pd.concat(equity_series, axis=1).sort_index()
        aligned = aligned.ffill().bfill()
        total = aligned.sum(axis=1)
        peak = total.cummax()
        drawdown = peak - total
        peak_safe = peak.where(peak != 0, 1.0)
        window_equity = pd.DataFrame(
            {
                "datetime": total.index,
                "total": total.to_numpy(),
                "drawdown": drawdown.to_numpy(),
                "drawdown_pct": (drawdown / peak_safe).to_numpy(),
            }
        )

        all_trades = (
            pd.concat(trade_frames, ignore_index=True)
            if trade_frames
            else pd.DataFrame(columns=["symbol", "direction", "pnl", "rejected"])
        )
        from easy_tdx.backtest.performance import PerformanceAnalyzer

        perf = PerformanceAnalyzer(equity_curve=window_equity, trades=all_trades).compute()

        return WalkForwardWindow(
            index=index,
            start=window_start.strftime("%Y-%m-%d"),
            end=window_end.strftime("%Y-%m-%d"),
            bars=int(e - s),
            total_return=float(perf.get("total_return", 0.0)),
            sharpe=float(perf.get("sharpe", 0.0)),
            max_drawdown=float(perf.get("max_drawdown", 0.0)),
            total_trades=int(perf.get("total_trades", 0)),
            win_rate=float(perf.get("win_rate", 0.0)),
            performance={k: v for k, v in perf.items()},
        )
