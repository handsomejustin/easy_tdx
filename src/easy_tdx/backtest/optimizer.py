"""参数网格寻优器。

对单个策略的 1-2 个参数做网格搜索：遍历用户指定的取值列表的笛卡尔积，
每个组合跑一次回测，按 total_return 排序，返回排名 + 热力图矩阵。

设计镜像 :class:`~easy_tdx.backtest.combo.CombinationRunner` 的枚举/排序模式，
但遍历的是参数组合而非策略组合。网格大小硬上限 ``MAX_GRID_POINTS`` 防组合爆炸。

用法::

    from easy_tdx.backtest.optimizer import ParamGridOptimizer

    opt = ParamGridOptimizer(
        strategy_name="ma_cross",
        param_grid={"fast": [5, 10, 20], "slow": [10, 20, 30]},
        df=df,
        cash=100000,
    )
    result = opt.run()
    print(result.best.params, result.best.total_return)
"""

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.types import BacktestResult

logger = logging.getLogger(__name__)

# 网格点上限：防止组合爆炸。3 参数各 6 值 = 216 已接近上限。
MAX_GRID_POINTS = 200


@dataclass
class GridPointResult:
    """单个网格点的回测结果摘要。

    Attributes:
        params: 该点的参数取值（如 {"fast": 10, "slow": 20}）
        total_return: 总收益率
        sharpe: 夏普比率
        max_drawdown: 最大回撤
        total_trades: 总交易笔数
        win_rate: 胜率（0-1）
        profit_factor: 盈亏比
    """

    params: dict[str, Any]
    total_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0


@dataclass
class OptimizeResult:
    """网格寻优完整结果。

    Attributes:
        strategy: 策略名
        param_names: 寻优的参数名列表（1-2 个，决定热力图维度）
        results: 所有网格点结果，按 total_return 降序排列
        best: 最优点（results[0] 的引用）
        heatmap: 2 参数时的热力图矩阵（x/y 轴取值 + cell 收益率）；1 参数或空时为 None
    """

    strategy: str
    param_names: list[str]
    results: list[GridPointResult]
    best: GridPointResult | None = None
    heatmap: dict[str, Any] | None = None
    cache_stats: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容字典。"""
        import math

        def clean(v: Any) -> Any:
            if isinstance(v, float) and not math.isfinite(v):
                return None
            return v

        return {
            "strategy": self.strategy,
            "param_names": self.param_names,
            "results": [
                {
                    "params": r.params,
                    "total_return": clean(r.total_return),
                    "sharpe": clean(r.sharpe),
                    "max_drawdown": clean(r.max_drawdown),
                    "total_trades": r.total_trades,
                    "win_rate": clean(r.win_rate),
                    "profit_factor": clean(r.profit_factor),
                }
                for r in self.results
            ],
            "best": (
                {
                    "params": self.best.params,
                    "total_return": clean(self.best.total_return),
                    "sharpe": clean(self.best.sharpe),
                    "max_drawdown": clean(self.best.max_drawdown),
                    "total_trades": self.best.total_trades,
                    "win_rate": clean(self.best.win_rate),
                    "profit_factor": clean(self.best.profit_factor),
                }
                if self.best
                else None
            ),
            "heatmap": self.heatmap,
            "cache_stats": self.cache_stats,
        }


class ParamGridOptimizer:
    """参数网格寻优器。

    遍历 ``param_grid`` 的笛卡尔积，每个组合实例化策略 + 跑回测，
    收集指标后排序。复用同一份 DataFrame（引擎无跨 run 缓存，安全）。

    Args:
        strategy_name: 策略名（从注册表解析）
        param_grid: 参数取值网格，如 {"fast": [5,10,20], "slow": [10,20,30]}
        df: OHLCV DataFrame（所有网格点共用）
        cash: 初始资金
        commission: 佣金率
        min_commission: 最低佣金
        stamp_tax: 印花税
        slippage: 滑点
        execution: 成交模式
    """

    def __init__(
        self,
        strategy_name: str,
        param_grid: dict[str, list[Any]],
        df: pd.DataFrame,
        cash: float = 1_000_000.0,
        commission: float = 0.0003,
        min_commission: float = 5.0,
        stamp_tax: float = 0.001,
        slippage: float = 0.0,
        execution: str = "next_open",
        workers: int = 1,
    ) -> None:
        """Initialize.

        Args:
            strategy_name: 策略名（从注册表解析）
            param_grid: 参数取值网格，如 {"fast": [5,10,20], "slow": [10,20,30]}
            df: OHLCV DataFrame（所有网格点共用）
            cash: 初始资金
            commission: 佣金率
            min_commission: 最低佣金
            stamp_tax: 印花税
            slippage: 滑点
            execution: 成交模式
            workers: 并行度。1（默认）= 进程内串行 + 指标缓存跨网格点复用
                （两段式加速）；≥2 = ProcessPoolExecutor 进程级并行（回测
                持 GIL，线程无加速；并行模式下各进程独立缓存）。
        """
        size = 1
        for vals in param_grid.values():
            size *= len(vals)
        if size > MAX_GRID_POINTS:
            raise ValueError(f"网格大小 {size} 超过上限 {MAX_GRID_POINTS}，请减少参数取值数量")
        if size == 0:
            raise ValueError("param_grid 不能有空取值列表")

        self._strategy_name = strategy_name
        self._param_grid = param_grid
        self._df = df
        self._cash = cash
        self._commission = commission
        self._min_commission = min_commission
        self._stamp_tax = stamp_tax
        self._slippage = slippage
        self._execution = execution
        self._workers = max(int(workers), 1)
        # 两段式加速：指标层缓存（workers==1 时生效；并行模式各进程独立）
        self._cache: Any = None
        self._cache_stats: dict[str, Any] | None = None

    def run(self) -> OptimizeResult:
        """执行网格寻优，返回排序后的结果。"""
        # 延迟导入避免循环依赖
        from easy_tdx.backtest.strategies import get_registry

        entry = get_registry().get(self._strategy_name)
        param_names = list(self._param_grid.keys())
        value_lists = [self._param_grid[name] for name in param_names]
        combos = [dict(zip(param_names, c, strict=True)) for c in itertools.product(*value_lists)]

        if self._workers >= 2:
            results = self._run_parallel(combos)
        else:
            results = self._run_serial(combos, entry)

        # 按 total_return 降序
        results.sort(key=lambda r: r.total_return, reverse=True)

        best = results[0] if results else None
        heatmap = self._build_heatmap(results, param_names) if len(param_names) == 2 else None

        out = OptimizeResult(
            strategy=self._strategy_name,
            param_names=param_names,
            results=results,
            best=best,
            heatmap=heatmap,
            cache_stats=self._cache_stats,
        )
        return out

    def _run_serial(self, combos: list[dict[str, Any]], entry: Any) -> list[GridPointResult]:
        """进程内串行 + 指标缓存复用。"""
        from easy_tdx.backtest.indicator_cache import IndicatorCache

        cache = IndicatorCache()
        self._cache = cache
        results: list[GridPointResult] = []
        for params in combos:
            r = self._evaluate_point(entry, params, cache)
            if r is not None:
                results.append(r)
        self._cache_stats = cache.stats()
        return results

    def _run_parallel(self, combos: list[dict[str, Any]]) -> list[GridPointResult]:
        """进程池并行（Windows spawn 要求 worker 函数与参数可 pickle）。"""
        import concurrent.futures

        jobs = [
            (
                self._strategy_name,
                params,
                self._df,
                self._cash,
                self._commission,
                self._min_commission,
                self._stamp_tax,
                self._slippage,
                self._execution,
            )
            for params in combos
        ]
        results: list[GridPointResult] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=self._workers) as pool:
            for r in pool.map(_optimize_grid_point, jobs, chunksize=4):
                if r is not None:
                    results.append(r)
        return results

    def _evaluate_point(
        self, entry: Any, params: dict[str, Any], cache: Any
    ) -> GridPointResult | None:
        """评估单个网格点（无效组合/回测失败返回 None）。"""
        try:
            # 寻优时跳过参数范围检查——探索超范围值是寻优的目的；
            # 但跨参数语义约束（如 fast<slow）仍生效，倒挂组合在此被跳过
            strategy = entry.build(params, skip_bounds=True)
        except ValueError:
            # 预期内的无效组合（语义倒挂/相等），info 级即可，无需堆栈
            logger.info("网格点 %s 语义无效，跳过", params)
            return None
        try:
            engine = BacktestEngine(
                strategy=strategy,
                cash=self._cash,
                commission=self._commission,
                min_commission=self._min_commission,
                stamp_tax=self._stamp_tax,
                slippage=self._slippage,
                execution=self._execution,
                indicator_cache=cache,
            )
            bt_result: BacktestResult = engine.run(self._df)
            perf = bt_result.performance
            return GridPointResult(
                params=params,
                total_return=perf.get("total_return", 0.0),
                sharpe=perf.get("sharpe", 0.0),
                max_drawdown=perf.get("max_drawdown", 0.0),
                total_trades=int(perf.get("total_trades", 0)),
                win_rate=perf.get("win_rate", 0.0),
                profit_factor=perf.get("profit_factor", 0.0),
            )
        except Exception:  # noqa: BLE001 — 单点失败不中断整个网格
            logger.warning("网格点 %s 回测失败，跳过", params, exc_info=True)
            return None

    def _build_heatmap(
        self,
        results: list[GridPointResult],
        param_names: list[str],
    ) -> dict[str, Any]:
        """2 参数时构建热力图矩阵：x=参数1取值，y=参数2取值，cell=total_return。

        Returns:
            {"x": [...], "y": [...], "data": [[x_idx, y_idx, value], ...]}
        """
        x_name, y_name = param_names
        x_vals = sorted(set(self._param_grid[x_name]))
        y_vals = sorted(set(self._param_grid[y_name]))
        x_idx = {v: i for i, v in enumerate(x_vals)}
        y_idx = {v: i for i, v in enumerate(y_vals)}

        data: list[list[Any]] = []
        for r in results:
            x = r.params.get(x_name)
            y = r.params.get(y_name)
            if x not in x_idx or y not in y_idx:
                continue
            data.append([x_idx[x], y_idx[y], r.total_return])

        return {"x_name": x_name, "y_name": y_name, "x": x_vals, "y": y_vals, "data": data}


def _optimize_grid_point(job: tuple[Any, ...]) -> GridPointResult | None:
    """进程池 worker：在子进程内评估单个网格点（模块级，可 pickle）。

    job = (strategy_name, params, df, cash, commission, min_commission,
           stamp_tax, slippage, execution)
    """
    (name, params, df, cash, commission, min_commission, stamp_tax, slippage, execution) = job
    from easy_tdx.backtest.strategies import get_registry

    try:
        entry = get_registry().get(name)
        strategy = entry.build(params, skip_bounds=True)
    except ValueError:
        return None
    try:
        engine = BacktestEngine(
            strategy=strategy,
            cash=cash,
            commission=commission,
            min_commission=min_commission,
            stamp_tax=stamp_tax,
            slippage=slippage,
            execution=execution,
        )
        perf = engine.run(df).performance
        return GridPointResult(
            params=params,
            total_return=perf.get("total_return", 0.0),
            sharpe=perf.get("sharpe", 0.0),
            max_drawdown=perf.get("max_drawdown", 0.0),
            total_trades=int(perf.get("total_trades", 0)),
            win_rate=perf.get("win_rate", 0.0),
            profit_factor=perf.get("profit_factor", 0.0),
        )
    except Exception:  # noqa: BLE001
        logger.warning("网格点 %s 回测失败（并行 worker），跳过", params, exc_info=True)
        return None
