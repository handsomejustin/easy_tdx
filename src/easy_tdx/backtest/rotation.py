"""轮动组合回测引擎（v1.27 新增）。

按排名定期换仓的组合策略回测（借鉴 indicator-lab 的动态组合语义）：

- **排名**：每个调仓日用 ``score_fn`` 对股票池逐标的打分（只用截至当日
  收盘的数据，无未来泄漏），分数可来自动量、因子或**通达信公式的数值
  输出**（:func:`formula_score`）；
- **固定槽位等额**：资金分为 ``slots`` 个槽位，每槽 = 当前净值 / 槽数；
- **卖出自动补位**：持仓跌出前 ``keep_rank`` 名（默认 = 槽数，可加缓冲
  池降低换手）→ 次日开盘卖出，空出的槽位买入新的前排名（次日开盘）；
- **刷新频率**：``daily`` / ``weekly``（每周首个交易日）/ ``monthly``
  （每月首个交易日）；
- **槽内止盈止损**：收盘价较成本跌破 ``stop_loss`` 或涨破 ``take_profit``
  → 次日开盘卖出（不做盘中路径假设，全部次开成交，口径与主引擎一致）。

执行语义：调仓信号在 T 日收盘产生、T+1 开盘成交（next_open），复用
主引擎的绩效分析器（19 项指标）与组合评级。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.backtest.performance import PerformanceAnalyzer

__all__ = ["RotationEngine", "RotationResult", "momentum_score", "formula_score"]

ScoreFn = Callable[[pd.DataFrame], float]


def momentum_score(period: int = 20) -> ScoreFn:
    """动量打分：最近 ``period`` 根涨幅（越高排名越靠前）。"""

    def _score(df: pd.DataFrame) -> float:
        close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float)
        if len(close) < period + 1:
            return 0.0
        prev = close[-period - 1]
        return float(close[-1] / prev - 1.0) if prev > 0 else 0.0

    return _score


def formula_score(formula_text_or_compiled: Any, value_col: str | None = None) -> ScoreFn:
    """用通达信公式的数值输出做打分（与公式模块无缝联动）。"""
    from easy_tdx.formula import CompiledFormula, compile_formula

    compiled = (
        formula_text_or_compiled
        if isinstance(formula_text_or_compiled, CompiledFormula)
        else compile_formula(formula_text_or_compiled)
    )

    def _score(df: pd.DataFrame) -> float:
        result = compiled.compute(df)
        if not result.values:
            return 0.0
        col = value_col or result.values[-1]
        arr = np.asarray(result.columns.get(col, [0.0]), dtype=float)
        v = arr[-1] if len(arr) else 0.0
        return float(v) if math.isfinite(v) else 0.0

    return _score


@dataclass
class _Position:
    symbol: str
    shares: float = 0.0
    cost: float = 0.0  # 平均成本（含费用近似）

    @property
    def value_hint(self) -> float:
        return self.shares * self.cost


@dataclass
class RotationResult:
    """轮动回测结果。"""

    performance: dict[str, Any] = field(default_factory=dict)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    final_holdings: dict[str, dict[str, float]] = field(default_factory=dict)
    rebalance_dates: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "performance": _clean(self.performance),
            "equity_curve": _clean(self.equity_curve),
            "trades": _clean(self.trades),
            "final_holdings": _clean(self.final_holdings),
            "n_rebalances": len(self.rebalance_dates),
            "rebalance_dates": self.rebalance_dates,
            "config": _clean(self.config),
        }


def _clean(obj: Any) -> Any:
    """numpy/Timestamp/NaN → JSON 原生（递归）。"""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if obj is None or isinstance(obj, str | int | bool):
        return obj
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class RotationEngine:
    """排名轮动组合回测。

    Example::
        engine = RotationEngine(
            stock_dfs={"SH:600519": df1, "SZ:000858": df2, ...},
            score_fn=momentum_score(20),
            slots=3,
            refresh="weekly",
        )
        result = engine.run()
        result.performance["total_return"]
    """

    def __init__(
        self,
        stock_dfs: dict[str, pd.DataFrame],
        score_fn: ScoreFn,
        slots: int = 5,
        refresh: str = "weekly",
        keep_rank: int | None = None,
        cash: float = 1_000_000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        max_score_history: int = 250,
    ) -> None:
        """Initialize.

        Args:
            stock_dfs: 股票池（symbol → K 线 DataFrame，时间升序）。
            score_fn: 打分函数 ``f(df_prefix) -> float``（只喂截至当日的数据）。
            slots: 持仓槽位数（等额分配）。
            refresh: 调仓频率 ``daily`` / ``weekly`` / ``monthly``。
            keep_rank: 跌出前 N 名才卖出（默认 = slots，缓冲池可设更大）。
            cash: 初始资金。
            commission / min_commission / stamp_tax: 费率（卖出收印花税）。
            stop_loss / take_profit: 槽内止损/止盈（比例，如 0.1 = ±10%）。
            max_score_history: 预计算的打分滚动窗口上限（性能保护）。
        """
        if not stock_dfs:
            raise ValueError("stock_dfs 不能为空")
        if slots < 1:
            raise ValueError("slots 必须 ≥ 1")
        if refresh not in ("daily", "weekly", "monthly"):
            raise ValueError(f"refresh 只支持 daily/weekly/monthly，当前 {refresh}")
        self._dfs = {sym: self._normalize(df) for sym, df in stock_dfs.items() if len(df) >= 2}
        if len(self._dfs) < 2:
            raise ValueError("股票池有效标的不足 2 只（至少 2 根 K 线）")
        self._score_fn = score_fn
        self._slots = int(slots)
        self._refresh = refresh
        self._keep_rank = keep_rank or self._slots
        self._cash = float(cash)
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._stop_loss = stop_loss
        self._take_profit = take_profit
        self._max_history = max_score_history

    # ── 主流程 ───────────────────────────────────────────────────────────────

    def run(self) -> RotationResult:
        result = RotationResult(
            config={
                "slots": self._slots,
                "refresh": self._refresh,
                "keep_rank": self._keep_rank,
                "cash": self._cash,
                "commission": self._commission,
                "stop_loss": self._stop_loss,
                "take_profit": self._take_profit,
            }
        )
        calendar = self._common_calendar()
        if len(calendar) < 10:
            return result

        cash = self._cash
        positions: dict[str, _Position] = {}
        pending: list[tuple[str, str, str]] = []  # (symbol, direction, reason) 次开执行
        equity_records: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        rebalances: list[str] = []

        # 每标的有效 bar 指针：date -> 各标的最近一根 ≤ d 的 bar
        pointers = {sym: -1 for sym in self._dfs}

        prev_key: tuple[int, ...] | None = None
        peak = self._cash
        equity_total = self._cash  # 最近一日净值（槽位预算基准）

        for day_i, d in enumerate(calendar):
            d_str = d.strftime("%Y-%m-%d")

            # 1. 推进各标的指针到 ≤ d 的最新一根
            bar_today: dict[str, pd.Series] = {}
            for sym, df in self._dfs.items():
                dts = self._dt_index(sym)
                while pointers[sym] + 1 < len(dts) and dts[pointers[sym] + 1] <= d:
                    pointers[sym] += 1
                if pointers[sym] >= 0:
                    bar_today[sym] = df.iloc[pointers[sym]]

            # 2. 次开执行昨日信号（用当日开盘价）
            for sym, direction, reason in pending:
                if sym not in bar_today:
                    continue
                price = float(bar_today[sym]["open"])
                if not math.isfinite(price) or price <= 0:
                    continue
                if direction == "SELL" and sym in positions:
                    pos = positions.pop(sym)
                    gross = pos.shares * price
                    fee = self._fee(gross, is_sell=True)
                    cash += gross - fee
                    pnl = (price - pos.cost) * pos.shares - fee
                    trades.append(
                        self._trade_row(
                            day_i, d_str, sym, "SELL", pos.shares, price, fee, pnl, reason=reason
                        )
                    )
                elif direction == "BUY" and sym not in positions and cash > 0:
                    budget = self._slot_budget(cash, equity_total, len(positions))
                    if budget <= price * 100:
                        continue
                    shares = math.floor(budget / (price * (1 + self._commission)) / 100) * 100
                    if shares <= 0:
                        continue
                    gross = shares * price
                    fee = self._fee(gross, is_sell=False)
                    cash -= gross + fee
                    positions[sym] = _Position(
                        symbol=sym, shares=shares, cost=(gross + fee) / shares
                    )
                    trades.append(
                        self._trade_row(
                            day_i, d_str, sym, "BUY", shares, price, fee, 0.0, reason=reason
                        )
                    )
            pending = []

            # 3. 止盈止损检查（收盘口径，次日执行）
            for sym in list(positions):
                if sym not in bar_today:
                    continue
                close = float(bar_today[sym]["close"])
                cost = positions[sym].cost
                if self._stop_loss is not None and close <= cost * (1 - self._stop_loss):
                    pending.append((sym, "SELL", "stop_loss"))
                elif self._take_profit is not None and close >= cost * (1 + self._take_profit):
                    pending.append((sym, "SELL", "take_profit"))

            # 4. 调仓判定
            key = (
                (d.isocalendar()[0], d.isocalendar()[1])
                if self._refresh == "weekly"
                else ((d.year, d.month) if self._refresh == "monthly" else (day_i,))
            )
            is_rebalance = key != prev_key
            prev_key = key
            if is_rebalance and day_i >= 1:
                rebalances.append(d_str)
                ranked = self._rank_all(pointers, d)
                top_keep = [s for s, _ in ranked[: self._keep_rank]]
                top_slots = [s for s, _ in ranked[: self._slots]]
                # 卖出：跌出 keep_rank 的持仓
                for sym in list(positions):
                    if sym not in top_keep and all(p[0] != sym or p[1] != "SELL" for p in pending):
                        pending.append((sym, "SELL", "rank_exit"))
                # 买入：前 slots 中未持有的（等空出的槽位）
                free = self._slots - len(positions) + sum(1 for p in pending if p[1] == "SELL")
                for sym in top_slots:
                    if free <= 0:
                        break
                    if sym not in positions and all(p[0] != sym or p[1] != "BUY" for p in pending):
                        pending.append((sym, "BUY", "rotation"))
                        free -= 1

            # 5. 收盘估值（净值曲线点）
            position_value = 0.0
            for sym, pos in positions.items():
                if sym in bar_today:
                    position_value += pos.shares * float(bar_today[sym]["close"])
            total = cash + position_value
            equity_total = total
            peak = max(peak, total)
            dd_pct = (peak - total) / peak if peak > 0 else 0.0
            equity_records.append(
                {
                    "datetime": d_str,
                    "cash": cash,
                    "position_value": position_value,
                    "total": total,
                    "drawdown": peak - total,
                    "drawdown_pct": dd_pct,
                }
            )

        result.equity_curve = equity_records
        result.trades = trades
        result.rebalance_dates = rebalances
        result.final_holdings = {
            sym: {"shares": pos.shares, "cost": pos.cost} for sym, pos in positions.items()
        }
        result.performance = self._analyze(equity_records, trades)
        return result

    # ── 辅助 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        dt_col = "datetime" if "datetime" in out.columns else "date"
        out["_ts"] = pd.to_datetime(out[dt_col])
        return out.sort_values("_ts").reset_index(drop=True)

    def _common_calendar(self) -> pd.DatetimeIndex:
        all_dts = pd.DatetimeIndex([])
        for sym in self._dfs:
            all_dts = all_dts.union(self._dt_index(sym))
        return all_dts.sort_values()

    def _dt_index(self, sym: str) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self._dfs[sym]["_ts"])

    def _rank_all(self, pointers: dict[str, int], d: Any) -> list[tuple[str, float]]:
        """对全部标的按截至 d 的前缀数据打分并降序排名。"""
        scored: list[tuple[str, float]] = []
        for sym, df in self._dfs.items():
            idx = pointers[sym]
            if idx < 5:
                scored.append((sym, 0.0))
                continue
            start = max(0, idx - self._max_history)
            prefix = df.iloc[start : idx + 1].drop(columns=["_ts"], errors="ignore")
            try:
                s = float(self._score_fn(prefix))
            except Exception:  # noqa: BLE001 — 单标的打分失败按 0 处理
                s = 0.0
            scored.append((sym, s if math.isfinite(s) else 0.0))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _slot_budget(self, cash: float, equity_total: float, held: int) -> float:
        """空槽预算 = 当前净值 / 槽数（等额口径），受剩余现金约束。"""
        target = equity_total / self._slots
        return max(0.0, min(target, cash))

    def _fee(self, gross: float, *, is_sell: bool) -> float:
        fee = max(gross * self._commission, self._min_commission)
        if is_sell:
            fee += gross * self._stamp_tax
        return fee

    @staticmethod
    def _trade_row(
        day: int,
        d_str: str,
        sym: str,
        direction: str,
        size: float,
        price: float,
        fee: float,
        pnl: float,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "datetime": d_str,
            "symbol": sym,
            "direction": direction,
            "size": size,
            "price": price,
            "commission": fee,
            "slippage": 0.0,
            "pnl": pnl,
            "cost_basis": 0.0 if direction == "BUY" else price * size,
            "rejected": False,
            "reason": reason,
        }

    @staticmethod
    def _analyze(
        equity_records: list[dict[str, Any]], trades: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """复用主引擎绩效分析器（19 项指标）。"""
        if len(equity_records) < 2:
            return {}
        equity = pd.DataFrame(equity_records)
        trades_df = (
            pd.DataFrame(trades)
            if trades
            else pd.DataFrame(
                {"datetime": [], "direction": [], "pnl": [], "rejected": [], "size": []}
            )
        )
        trades_df["rejected"] = trades_df.get("rejected", False)
        analyzer = PerformanceAnalyzer(equity, trades_df, risk_free_rate=0.03)
        return dict(analyzer.compute())
