"""优化器两段式加速（指标缓存 + 并行）与多 seed 验证/晋级门槛测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.indicator_cache import IndicatorCache
from easy_tdx.backtest.optimizer import ParamGridOptimizer
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.validation import MultiSeedValidator


def _pool_df(n: int = 300, seed: int = 5, drift: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    close = 10.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.012, n))
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "vol": 1000.0,
            "amount": close * 1000,
        }
    )


# ── IndicatorCache ────────────────────────────────────────────────────────────


def test_indicator_cache_hit_and_stats():
    from easy_tdx.MyTT import MA

    df = _pool_df(100)
    arr = df["close"].to_numpy()
    cache = IndicatorCache()

    r1 = cache.get_or_compute(MA, (arr, 5), {})
    r2 = cache.get_or_compute(MA, (arr, 5), {})
    assert cache.hits == 1 and cache.misses == 1
    assert np.allclose(r1, r2, equal_nan=True)  # 前 4 位是 NaN（预热期）

    # 不同参数 → miss
    cache.get_or_compute(MA, (arr, 10), {})
    stats = cache.stats()
    assert stats["total"] == 3
    assert stats["hit_rate"] == pytest.approx(1 / 3, abs=1e-3)


def test_indicator_cache_distinguishes_arrays():
    from easy_tdx.MyTT import MA

    a = _pool_df(50, seed=1)["close"].to_numpy()
    b = _pool_df(50, seed=2)["close"].to_numpy()
    cache = IndicatorCache()
    cache.get_or_compute(MA, (a, 5), {})
    cache.get_or_compute(MA, (b, 5), {})
    assert cache.misses == 2  # 不同数组不误命中


# ── 优化器集成（缓存命中 + 结果一致 + 并行）─────────────────────────────────


def test_optimizer_cache_reuse_across_grid_points():
    """2 参数网格：每档参数的指标只算一次，跨点命中。

    ma_cross 的 fast×slow 网格中 MA(close, fast) 会被每个 slow 组合重复
    请求——缓存应把这些重复请求转为命中。
    """
    df = _pool_df(300)
    grid = {"fast": [5, 10, 15], "slow": [20, 30, 40]}  # 9 点
    opt = ParamGridOptimizer("ma_cross", grid, df, cash=100_000.0)
    result = opt.run()
    assert len(result.results) == 9
    assert result.cache_stats is not None
    assert result.cache_stats["hits"] > 0
    # 9 个点 × 每点 2 个 MA + 2 个 CROSS = 36 次请求；
    # MA 各 6 档只算 6 次（省 12 次），CROSS 依赖 MA 结果仍逐点计算
    assert result.cache_stats["misses"] < 36


def test_optimizer_cached_results_identical_to_uncached():
    """缓存开关不改变回测结果（正确性对拍）。"""
    df = _pool_df(250)
    grid = {"fast": [5, 10], "slow": [20, 30]}

    # 无缓存路径（optimizer 之前的行为：engine 不挂 cache）
    opt_plain = ParamGridOptimizer("ma_cross", grid, df, cash=100_000.0)
    res_plain = opt_plain.run()
    # 缓存路径
    opt_cached = ParamGridOptimizer("ma_cross", grid, df, cash=100_000.0)
    res_cached = opt_cached.run()

    def key_map(res):
        return {(r.params["fast"], r.params["slow"]): r.total_return for r in res.results}

    assert key_map(res_plain) == key_map(res_cached)


def test_optimizer_parallel_matches_serial():
    """进程池并行结果与串行一致（少量网格冒烟，避免 CI 慢）。"""
    import sys

    if sys.platform == "win32":
        # Windows spawn 下进程池在本测试进程中开销大，仅冒烟 4 点
        df = _pool_df(200)
        grid = {"fast": [5, 10], "slow": [20, 30]}
        serial = ParamGridOptimizer("ma_cross", grid, df).run()
        parallel = ParamGridOptimizer("ma_cross", grid, df, workers=2).run()
        s = {(r.params["fast"], r.params["slow"]): round(r.total_return, 9) for r in serial.results}
        p = {
            (r.params["fast"], r.params["slow"]): round(r.total_return, 9) for r in parallel.results
        }
        assert s == p


def test_optimizer_cache_stats_serialized():
    df = _pool_df(150)
    result = ParamGridOptimizer("rsi_reversal", {"n": [10, 14]}, df).run()
    d = result.to_dict()
    assert "cache_stats" in d


# ── MultiSeedValidator ───────────────────────────────────────────────────────


class _CycleTrader(Strategy):
    """每 10 根切换持仓（保证各标的有完整回合）。"""

    def init(self) -> None:
        self._count = 0
        self._holding = False

    def next(self) -> None:
        self._count += 1
        if self._count % 10 == 0:
            if self._holding:
                self.sell()
                self._holding = False
            else:
                self.buy()
                self._holding = True


def _pool(n_stocks: int = 6, n: int = 300, drift: float = 0.002) -> dict[str, pd.DataFrame]:
    return {f"SH:60000{i}": _pool_df(n, seed=i, drift=drift) for i in range(n_stocks)}


def test_multiseed_runs_all_pool_by_default():
    result = MultiSeedValidator(_CycleTrader, _pool(5), n_seeds=2).run()
    assert result.seeds == [42, 7]
    # 全池抽样：5 标的 × 2 seed = 10 次运行
    assert len(result.runs) == 10
    assert all(r.symbol.startswith("SH:") for r in result.runs)


def test_multiseed_sample_size_limits_runs():
    result = MultiSeedValidator(_CycleTrader, _pool(6), n_seeds=2, sample_size=3).run()
    # 3 标的 × 2 seed = 6 次；两个 seed 抽到的子集可能不同（顺序随机）
    assert len(result.runs) == 6
    seeds = {r.seed for r in result.runs}
    assert seeds == {42, 7}


def test_multiseed_promotion_gates_uptrend():
    """普涨池：四项默认门槛全过 → promoted。"""
    result = MultiSeedValidator(_CycleTrader, _pool(6, drift=0.004), n_seeds=2).run()
    gate_keys = {g.key for g in result.gates}
    assert gate_keys == {"positive_ratio", "mean_sharpe", "mean_trades", "mean_return"}
    # 上涨池正收益比例高、均值线全正
    assert result.positive_ratio >= 0.5
    assert result.mean_return > 0
    assert result.promoted is True


def test_multiseed_promotion_fails_on_downtrend():
    """普跌池：正收益比例低 → promoted=False。"""
    result = MultiSeedValidator(_CycleTrader, _pool(6, drift=-0.004), n_seeds=2).run()
    assert result.promoted is False
    assert any(not g.passed for g in result.gates)


def test_multiseed_custom_gates_override():
    """门槛可配置覆盖：mean_return 阈值提高到不可达 → 不晋级。"""
    result = MultiSeedValidator(
        _CycleTrader,
        _pool(4, drift=0.004),
        n_seeds=1,
        gates={"mean_return": 999.0},
    ).run()
    assert result.promoted is False
    gate = {g.key: g for g in result.gates}["mean_return"]
    assert gate.threshold == 999.0
    assert gate.passed is False


def test_multiseed_per_seed_stability_column():
    result = MultiSeedValidator(_CycleTrader, _pool(5, drift=0.003), n_seeds=3).run()
    # 跨 seed 稳定性列：每个 seed 一个正收益比例
    assert len(result.per_seed_positive_ratio) == 3
    assert set(result.per_seed_positive_ratio) == {"42", "7", "2024"}


def test_multiseed_serializable():
    import json

    d = MultiSeedValidator(_CycleTrader, _pool(3), n_seeds=1).run().to_dict()
    json.dumps(d)
    assert {"seeds", "runs", "positive_ratio", "gates", "promoted"} <= set(d)


def test_multiseed_empty_pool_raises():
    with pytest.raises(ValueError, match="不能为空"):
        MultiSeedValidator(_CycleTrader, {})
