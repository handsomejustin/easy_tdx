"""多 seed 验证 + 晋级门槛（v1.25 新增）。

单标的好收益可能是「运气」。backtest-system 的 ``multi_seed_validate`` /
``promotion_ok`` 思路：同一策略在**多组随机股票样本**上重复跑，用跨样本
稳定性（正收益比例、均值/中位数收益、夏普稳定性）代替单次成绩；只有通过
一组可配置的**晋级门槛**，策略才被认为「值得进入下一轮迭代」。

四项默认门槛（全部可配置，任一不达标即 ``promoted=False``）：

1. ``positive_ratio``：跨 (seed × 标的) 全部运行中收益 > 0 的比例 ≥ 0.5；
2. ``mean_sharpe``：平均夏普 > 0；
3. ``mean_trades``：平均完成交易笔数 ≥ 5（样本充分性）；
4. ``mean_return``：平均收益 > 0。

多 seed 的意义：不同 seed 抽到不同股票子集，若策略只对某几只票有效
（标的运气），跨 seed 的正收益比例会明显低于单 seed——这正是门槛要拦的。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategy import Strategy

__all__ = ["PromotionGate", "RunSummary", "MultiSeedResult", "MultiSeedValidator"]


@dataclass
class PromotionGate:
    """单条晋级门槛。"""

    key: str
    threshold: float
    actual: float
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "threshold": self.threshold,
            "actual": round(self.actual, 6),
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class RunSummary:
    """单次 (seed, 标的) 回测摘要。"""

    seed: int
    symbol: str
    total_return: float
    sharpe: float
    max_drawdown: float
    total_trades: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "symbol": self.symbol,
            "total_return": self.total_return,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "total_trades": self.total_trades,
        }


@dataclass
class MultiSeedResult:
    """多 seed 验证结果。"""

    seeds: list[int] = field(default_factory=list)
    runs: list[RunSummary] = field(default_factory=list)
    positive_ratio: float = 0.0
    mean_return: float = 0.0
    median_return: float = 0.0
    mean_sharpe: float = 0.0
    mean_trades: float = 0.0
    # 各 seed 的正收益比例（跨 seed 稳定性列）
    per_seed_positive_ratio: dict[str, float] = field(default_factory=dict)
    gates: list[PromotionGate] = field(default_factory=list)
    promoted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": self.seeds,
            "runs": [r.to_dict() for r in self.runs],
            "n_runs": len(self.runs),
            "positive_ratio": round(self.positive_ratio, 4),
            "mean_return": round(self.mean_return, 6),
            "median_return": round(self.median_return, 6),
            "mean_sharpe": round(self.mean_sharpe, 4),
            "mean_trades": round(self.mean_trades, 2),
            "per_seed_positive_ratio": {
                k: round(v, 4) for k, v in self.per_seed_positive_ratio.items()
            },
            "gates": [g.to_dict() for g in self.gates],
            "promoted": self.promoted,
        }


class MultiSeedValidator:
    """多 seed 随机抽样验证器。

    Example::
        validator = MultiSeedValidator(
            strategy=MyStrategy,
            stock_dfs={"SH:600519": df1, "SZ:000001": df2, ...},
            n_seeds=3,
            sample_size=5,
        )
        result = validator.run()
        result.promoted  # 是否通过全部晋级门槛
    """

    DEFAULT_GATES: dict[str, float] = {
        "positive_ratio": 0.5,
        "mean_sharpe": 0.0,
        "mean_trades": 5.0,
        "mean_return": 0.0,
    }

    def __init__(
        self,
        strategy: type[Strategy] | Strategy,
        stock_dfs: dict[str, pd.DataFrame],
        n_seeds: int = 3,
        sample_size: int | None = None,
        gates: dict[str, float] | None = None,
        cash: float = 100000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        auto_fees: bool = True,
        seed_list: list[int] | None = None,
    ) -> None:
        """Initialize.

        Args:
            strategy: 策略类或实例。
            stock_dfs: 股票池（symbol → K 线 DataFrame）。
            n_seeds: 随机种子数（默认 3）。
            sample_size: 每个 seed 抽取的标的数（None = 全池）。
            gates: 晋级门槛覆盖（键见 DEFAULT_GATES，未给的用默认）。
            auto_fees: 默认 True——股票池跨品种时按各自品种计费更真实。
            seed_list: 显式种子列表（默认 [42, 7, 2024, ...] 前 n 个）。
        """
        if not stock_dfs:
            raise ValueError("stock_dfs 不能为空")
        self._strategy = strategy
        self._stock_dfs = stock_dfs
        self._n_seeds = max(int(n_seeds), 1)
        self._sample_size = sample_size
        self._gates = {**self.DEFAULT_GATES, **(gates or {})}
        self._engine_kwargs: dict[str, Any] = {
            "cash": cash,
            "commission": commission,
            "min_commission": min_commission,
            "stamp_tax": stamp_tax,
            "slippage": slippage,
            "execution": execution,
            "auto_fees": auto_fees,
        }
        default_seeds = [42, 7, 2024, 99, 123]
        self._seeds = (
            list(seed_list)[: self._n_seeds] if seed_list else default_seeds[: self._n_seeds]
        )
        while len(self._seeds) < self._n_seeds:
            self._seeds.append(len(self._seeds) * 31 + 17)

    def run(self) -> MultiSeedResult:
        """执行多 seed 验证。"""
        result = MultiSeedResult(seeds=list(self._seeds))
        symbols = list(self._stock_dfs.keys())

        for seed in self._seeds:
            rng = random.Random(seed)
            sample = list(symbols)
            rng.shuffle(sample)
            if self._sample_size is not None:
                sample = sample[: min(self._sample_size, len(sample))]
            seed_returns: list[float] = []
            for sym in sample:
                summary = self._run_one(seed, sym)
                if summary is None:
                    continue
                result.runs.append(summary)
                seed_returns.append(summary.total_return)

            if seed_returns:
                pos = sum(1 for r in seed_returns if r > 0) / len(seed_returns)
                result.per_seed_positive_ratio[str(seed)] = pos

        self._aggregate(result)
        self._evaluate_gates(result)
        return result

    def _run_one(self, seed: int, symbol: str) -> RunSummary | None:
        """单 (seed, 标的) 回测（失败返回 None）。"""
        df = self._stock_dfs[symbol]
        if len(df) < 30:
            return None
        engine = BacktestEngine(
            strategy=self._strategy,
            symbol=symbol,
            **self._engine_kwargs,
        )
        try:
            perf = engine.run(df).performance
        except Exception:  # noqa: BLE001 — 单标失败不拖垮整组
            return None
        return RunSummary(
            seed=seed,
            symbol=symbol,
            total_return=float(perf.get("total_return", 0.0)),
            sharpe=float(perf.get("sharpe", 0.0)),
            max_drawdown=float(perf.get("max_drawdown", 0.0)),
            total_trades=int(perf.get("total_trades", 0)),
        )

    @staticmethod
    def _aggregate(result: MultiSeedResult) -> None:
        runs = result.runs
        if not runs:
            return
        rets = [r.total_return for r in runs]
        rets_sorted = sorted(rets)
        n = len(rets)
        mid = n // 2
        median = rets_sorted[mid] if n % 2 else (rets_sorted[mid - 1] + rets_sorted[mid]) / 2
        result.positive_ratio = sum(1 for r in rets if r > 0) / n
        result.mean_return = sum(rets) / n
        result.median_return = median
        result.mean_sharpe = sum(r.sharpe for r in runs) / n
        result.mean_trades = sum(r.total_trades for r in runs) / n

    def _evaluate_gates(self, result: MultiSeedResult) -> None:
        actuals = {
            "positive_ratio": result.positive_ratio,
            "mean_sharpe": result.mean_sharpe,
            "mean_trades": result.mean_trades,
            "mean_return": result.mean_return,
        }
        labels = {
            "positive_ratio": "正收益比例",
            "mean_sharpe": "平均夏普",
            "mean_trades": "平均交易笔数",
            "mean_return": "平均收益",
        }
        result.gates = []
        for key, threshold in self._gates.items():
            actual = actuals.get(key, 0.0)
            passed = actual >= threshold
            result.gates.append(
                PromotionGate(
                    key=key,
                    threshold=threshold,
                    actual=actual,
                    passed=passed,
                    detail=(
                        f"{labels.get(key, key)} {actual:.4f} {'≥' if passed else '<'} {threshold}"
                    ),
                )
            )
        result.promoted = bool(result.runs) and all(g.passed for g in result.gates)
