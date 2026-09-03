"""策略适配性评估（时间三段切分 + 可解释检查项，v1.25 新增）。

回测收益好可能只是「恰好适配了这段行情」。本模块把样本按时间切成
**训练 / 验证 / 测试**三段（默认 60/20/20）独立回测，用一组**可解释**的
检查项回答：策略赚的钱是「模式」还是「运气」？（借鉴 indicator-lab 的
策略适配性评估。）

与 :mod:`easy_tdx.backtest.walkforward` 的分工：WF 看的是「切 7 窗、逐窗
是否稳定」（时间稳定性切片更细）；适配性看的是「三段结构化切分 + 规则化
体检」（train 学到的模式在 valid/test 是否还成立）。两者互补，可同时报告。

检查项（8 项，每项独立可解释，附实际值）：

1. ``train_profitable`` 训练段收益 > 0（模式存在的前提）；
2. ``valid_profitable`` 验证段收益 > 0（模式非全样本偶然）；
3. ``test_profitable`` 测试段收益 > 0（最近样本仍成立）；
4. ``sign_consistent`` 三段收益同号（无「段间反转」，过拟合的典型症状）；
5. ``drawdown_bounded`` 测试段最大回撤不深于 -50%（尾部风险可控）；
6. ``train_enough_trades`` 训练段 ≥ 5 笔（样本充分性）；
7. ``test_active`` 测试段 ≥ 1 笔且交易频率不低于训练段的 1/3（未失效停摆）；
8. ``oos_sharpe_positive`` 验证+测试段合并夏普 > 0（样本外风险调整后仍赚）。

通过率 ≥ 75%（即 ≥ 6/8）且训练样本充分 → ``high_fitness = True``
（「高适配」标记）。

**滚动适配过滤**（防未来数据泄漏）：:meth:`FitnessEngine.evaluate_prefix`
只使用「截至某日**之前**」的已收盘数据计算适配分——组合轮动场景在每个
调仓日调用它，只用当时已知的信息决定是否启用该策略，杜绝 look-ahead。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.types import to_json_native

__all__ = ["FitnessCheck", "FitnessSegment", "FitnessReport", "FitnessEngine"]


@dataclass
class FitnessCheck:
    """单条检查项。"""

    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class FitnessSegment:
    """单个时间段的独立回测摘要。"""

    name: str  # train / valid / test
    start: str
    end: str
    bars: int
    total_return: float
    sharpe: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    performance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
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


@dataclass
class FitnessReport:
    """适配性评估结果。"""

    segments: list[FitnessSegment] = field(default_factory=list)
    checks: list[FitnessCheck] = field(default_factory=list)
    pass_ratio: float = 0.0  # 检查项通过率 0~1
    high_fitness: bool = False  # 「高适配」标记
    split: tuple[float, float, float] = (0.6, 0.2, 0.2)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    def segment_by_name(self, name: str) -> FitnessSegment | None:
        """按段名（train/valid/test）取段摘要，无该段时返回 None。"""
        return next((s for s in self.segments if s.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return dict(
            to_json_native(
                {
                    "segments": [s.to_dict() for s in self.segments],
                    "checks": [c.to_dict() for c in self.checks],
                    "pass_ratio": round(self.pass_ratio, 4),
                    "passed_count": self.passed_count,
                    "total_checks": len(self.checks),
                    "high_fitness": self.high_fitness,
                    "split": list(self.split),
                }
            )
        )


class FitnessEngine:
    """策略适配性评估引擎：三段切分 → 独立回测 → 检查项 → 高适配标记。

    Example:
        >>> eng = FitnessEngine(MyStrategy)
        >>> rep = eng.evaluate(df)
        >>> rep.high_fitness, rep.pass_ratio
        (True, 0.875)
    """

    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        split: tuple[float, float, float] = (0.6, 0.2, 0.2),
        context_bars: int = 60,
        cash: float = 100000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        symbol: str | None = None,
        auto_fees: bool = False,
        min_train_trades: int = 5,
        high_fitness_ratio: float = 0.75,
    ) -> None:
        """Initialize.

        Args:
            strategy: 策略类或实例（三段共用）。
            split: 三段占比（train/valid/test，默认 60/20/20）。
            context_bars: 每段前置上下文 K 线数（指标预热）。
            cash 及费率参数: 透传各段 :class:`BacktestEngine`。
            min_train_trades: 训练段最少交易笔数（样本充分性阈值）。
            high_fitness_ratio: 「高适配」要求的检查项通过率（默认 0.75）。
        """
        if abs(sum(split) - 1.0) > 1e-6 or any(s <= 0 for s in split):
            raise ValueError(f"split 必须为三个正数且和为 1，当前 {split}")
        self._strategy = strategy
        self._split = split
        self._context_bars = max(int(context_bars), 0)
        self._min_train_trades = int(min_train_trades)
        self._high_ratio = float(high_fitness_ratio)
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

    # ── 主入口 ───────────────────────────────────────────────────────────────

    def evaluate(self, df: pd.DataFrame) -> FitnessReport:
        """全样本三段评估（train/valid/test）。

        Args:
            df: 完整 K 线（时间升序）。

        Returns:
            :class:`FitnessReport`。数据不足（任一段 < 20 根）时返回空报告。
        """
        n = len(df)
        a = int(n * self._split[0])
        b = a + int(n * self._split[1])
        bounds = [("train", 0, a), ("valid", a, b), ("test", b, n)]
        return self._evaluate_bounds(df, bounds)

    def evaluate_prefix(self, df: pd.DataFrame, end_index: int) -> FitnessReport:
        """只用 ``df[:end_index]``（不含 end_index 当根）评估适配性。

        滚动适配过滤的基础原语：组合轮动在调仓日 t 调用时传 t 的下标，
        确保只使用 t 日**之前**的已收盘数据——无未来数据泄漏。

        Args:
            df: 完整 K 线（时间升序，仅取前缀，末根之后的行情不参与）。
            end_index: 前缀终点（不含）。

        Returns:
            :class:`FitnessReport`（对前缀做三段评估）。
        """
        return self.evaluate(df.iloc[:end_index])

    # ── 内部实现 ─────────────────────────────────────────────────────────────

    def _evaluate_bounds(
        self,
        df: pd.DataFrame,
        bounds: list[tuple[str, int, int]],
    ) -> FitnessReport:
        report = FitnessReport(split=self._split)
        segments: dict[str, FitnessSegment] = {}
        for name, s, e in bounds:
            if e - s < 20:  # 段太短，评估无效
                return report
            seg = self._run_segment(df, name, s, e)
            if seg is None:
                return report
            segments[name] = seg
        if len(segments) != 3:
            return report

        report.segments = [segments["train"], segments["valid"], segments["test"]]
        report.checks = self._build_checks(segments)
        report.pass_ratio = (
            sum(1 for c in report.checks if c.passed) / len(report.checks) if report.checks else 0.0
        )
        report.high_fitness = (
            report.pass_ratio >= self._high_ratio
            and segments["train"].total_trades >= self._min_train_trades
            and segments["test"].bars >= 20
        )
        return report

    def _run_segment(self, df: pd.DataFrame, name: str, s: int, e: int) -> FitnessSegment | None:
        """独立回测一段 [s, e)（前置上下文预热、段首空仓）。"""
        ctx_s = max(0, s - self._context_bars)
        lead = s - ctx_s
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
        except Exception:  # noqa: BLE001 — 段失败 → 整体评估无效
            return None
        perf = bt.performance
        dt_col = "datetime" if "datetime" in sub.columns else "date"
        vals = sub[dt_col].iloc[lead:]
        return FitnessSegment(
            name=name,
            start=(pd.Timestamp(vals.iloc[0]).strftime("%Y-%m-%d") if len(vals) else ""),
            end=(pd.Timestamp(vals.iloc[-1]).strftime("%Y-%m-%d") if len(vals) else ""),
            bars=int(e - s),
            total_return=float(perf.get("total_return", 0.0)),
            sharpe=float(perf.get("sharpe", 0.0)),
            max_drawdown=float(perf.get("max_drawdown", 0.0)),
            total_trades=int(perf.get("total_trades", 0)),
            win_rate=float(perf.get("win_rate", 0.0)),
            performance=dict(perf),
        )

    def _build_checks(self, seg: dict[str, FitnessSegment]) -> list[FitnessCheck]:
        """组装 8 项可解释检查。"""
        tr, va, te = seg["train"], seg["valid"], seg["test"]
        rets = [tr.total_return, va.total_return, te.total_return]
        signs = [r > 0 for r in rets]

        # 测试段交易频率（笔/百根）不低于训练段的 1/3
        tr_freq = tr.total_trades / max(tr.bars, 1)
        te_freq = te.total_trades / max(te.bars, 1)

        # 验证+测试合并夏普：按段等权近似（段收益/段波动不可直接合并，
        # 用两段夏普的 bars 加权平均替代，保持可解释）
        oos_sharpe = (va.sharpe * va.bars + te.sharpe * te.bars) / max(va.bars + te.bars, 1)

        return [
            FitnessCheck(
                name="train_profitable",
                passed=tr.total_return > 0,
                detail=f"训练段收益 {tr.total_return:+.2%}",
            ),
            FitnessCheck(
                name="valid_profitable",
                passed=va.total_return > 0,
                detail=f"验证段收益 {va.total_return:+.2%}",
            ),
            FitnessCheck(
                name="test_profitable",
                passed=te.total_return > 0,
                detail=f"测试段收益 {te.total_return:+.2%}",
            ),
            FitnessCheck(
                name="sign_consistent",
                passed=all(signs) or not any(signs),
                detail=f"三段收益符号 {[f'{r:+.2%}' for r in rets]}",
            ),
            FitnessCheck(
                name="drawdown_bounded",
                passed=te.max_drawdown > -0.5,
                detail=f"测试段最大回撤 {te.max_drawdown:.2%}（阈值 -50%）",
            ),
            FitnessCheck(
                name="train_enough_trades",
                passed=tr.total_trades >= self._min_train_trades,
                detail=f"训练段 {tr.total_trades} 笔（阈值 ≥{self._min_train_trades}）",
            ),
            FitnessCheck(
                name="test_active",
                passed=te.total_trades >= 1 and te_freq >= tr_freq / 3.0,
                detail=(
                    f"测试段 {te.total_trades} 笔（频率 {te_freq * 100:.2f} 笔/百根，"
                    f"训练段 {tr_freq * 100:.2f}）"
                ),
            ),
            FitnessCheck(
                name="oos_sharpe_positive",
                passed=oos_sharpe > 0,
                detail=f"验证+测试加权夏普 {oos_sharpe:+.2f}",
            ),
        ]


def rolling_fitness_scores(
    df: pd.DataFrame,
    strategy: type[Strategy] | Strategy,
    step: int = 60,
    min_prefix: int = 250,
    **engine_kwargs: Any,
) -> list[dict[str, Any]]:
    """滚动适配分序列（诊断/绘图用）。

    每 ``step`` 根 K 线取一个评估点，用该点**之前**的全部数据算三段适配分
    （无未来泄漏），输出 ``[{date, pass_ratio, high_fitness}, ...]`` 时间序列。
    组合轮动的逐日过滤请直接调 :meth:`FitnessEngine.evaluate_prefix`。

    Args:
        df: 完整 K 线（时间升序）。
        strategy: 策略类或实例。
        step: 评估点间隔（默认 60 根）。
        min_prefix: 首个评估点的最少前缀长度（默认 250 根）。
        **engine_kwargs: 透传 :class:`FitnessEngine` 构造参数。

    Returns:
        评估点列表（时间升序）。前缀不足或评估无效的点被跳过。
    """
    engine = FitnessEngine(strategy, **engine_kwargs)
    out: list[dict[str, Any]] = []
    dt_col = "datetime" if "datetime" in df.columns else "date"
    n = len(df)
    for i in range(min_prefix, n, step):
        rep = engine.evaluate_prefix(df, i)
        if not rep.segments:
            continue
        out.append(
            {
                "index": i,
                "date": pd.Timestamp(df[dt_col].iloc[i - 1]).strftime("%Y-%m-%d"),
                "pass_ratio": round(rep.pass_ratio, 4),
                "high_fitness": rep.high_fitness,
            }
        )
    return out
