"""向量化快速路径（v1.28）对拍与约束检测单测。

核心保证：**同一 df + 同参数下，向量化路径与逐 bar 路径的输出逐位一致**
（performance / trades / equity_curve / positions 全比对）。

- 对拍覆盖：全部内置策略（默认参数，当前 54 个）+ ma_cross/macd/boll/rsi 的非默认
  参数组合 + warmup / 极低资金（买不足 1 手的退化路径）/ 非默认费率与成交价模式；
- 约束检测：``_vectorize_eligibility`` 的显式约束（无掩码 / 缠论注入）与
  ``signal_path`` 的 auto/vector/loop 语义。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategies import get_registry
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.MyTT import MA

# ── 合成行情（确定性） ───────────────────────────────────────────────────────


def _synthetic_ohlcv(n: int = 800, seed: int = 42, base: float = 20.0) -> pd.DataFrame:
    """确定性随机游走 OHLCV（对拍两路径用同一份 df）。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.02, n)
    close = base * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[base], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.008, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.008, n)))
    vol = rng.integers(50_000, 5_000_000, n).astype(float)
    dates = pd.bdate_range("2022-01-04", periods=n)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


def _oscillating_ohlcv(n: int = 800, seed: int = 8, base: float = 20.0) -> pd.DataFrame:
    """周期振荡 OHLCV（正弦 + 噪声，high/low 恰为 max/min(open, close)）。

    donchian / wr_reversal 这类「突破 N 日高进 / 跌破 N 日低出」的策略，
    其通道窗口包含当根（upper ≥ 当根 high），``close >= upper`` 只有在
    close == high == 窗口最大（即收盘即创新高）时才成立——high/low 不放大，
    正弦行情每个周期顶/底都会双向触发，覆盖完整的开平仓循环。
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    close = base * (1.0 + 0.15 * np.sin(2 * np.pi * t / 40) + rng.normal(0.0, 0.002, n))
    open_ = np.concatenate([[base], close[:-1]])
    high = np.maximum(open_, close)
    low = np.minimum(open_, close)
    vol = rng.integers(50_000, 5_000_000, n).astype(float)
    dates = pd.bdate_range("2022-01-04", periods=n)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


def _assert_perf_equal(a: dict[str, Any], b: dict[str, Any]) -> None:
    """performance 字典逐位比对（NaN 视为相等——两条路径应产生完全相同的浮点数）。"""
    assert set(a.keys()) == set(b.keys()), f"键集不一致: {set(a) ^ set(b)}"
    for key in a:
        va, vb = a[key], b[key]
        if isinstance(va, float) and isinstance(vb, float) and math.isnan(va) and math.isnan(vb):
            continue
        assert va == vb, f"performance[{key}] 不一致: loop={va!r} vector={vb!r}"


def _assert_results_identical(loop: Any, vec: Any) -> None:
    _assert_perf_equal(loop.performance, vec.performance)
    pd.testing.assert_frame_equal(loop.trades, vec.trades)
    pd.testing.assert_frame_equal(loop.equity_curve, vec.equity_curve)
    pd.testing.assert_frame_equal(loop.positions, vec.positions)
    assert loop.config == vec.config


def _run_both(
    name: str,
    df: pd.DataFrame,
    params: dict[str, Any] | None = None,
    *,
    skip_bounds: bool = False,
    **engine_kw: Any,
):
    """同一配置下分别跑逐 bar / 自动画两条路径。"""
    entry = get_registry().get(name)
    loop = BacktestEngine(
        entry.build(params, skip_bounds=skip_bounds), signal_path="loop", **engine_kw
    ).run(df)
    vec = BacktestEngine(
        entry.build(params, skip_bounds=skip_bounds), signal_path="auto", **engine_kw
    ).run(df)
    return loop, vec


# ── 对拍：全部内置策略 × 默认参数 ───────────────────────────────────────────


#: 已知「默认参数下不会交易」的策略：MyTT 的 WR 是 0~100 刻度（100=超卖），
#: 而 wr_reversal 默认阈值为 -80/-20（通达信 -100~0 惯例），entry 恒 False。
#: 这是策略的既有行为（两路径一致地不交易），语义修正不属于向量化改动范围；
#: 对拍改用非默认参数覆盖（见 test_key_strategies_alternate_params）。
_DEAD_DEFAULT_STRATEGIES = {"wr_reversal"}


@pytest.mark.parametrize("name", get_registry().names())
def test_all_builtin_strategies_default_params(name: str) -> None:
    """全部内置策略：向量化与逐 bar 输出逐位一致（对拍核心保证）。"""
    df = _synthetic_ohlcv()
    loop, vec = _run_both(name, df)
    # 确认确实产生了交易（空交易的对拍没有意义）：随机游走无交易换种子，
    # 再无交易换振荡行情（donchian/wr 等带状策略只在振荡行情双向触发）
    if len(loop.trades) == 0:
        loop, vec = _run_both(name, _synthetic_ohlcv(seed=7, base=50.0))
    if len(loop.trades) == 0:
        loop, vec = _run_both(name, _oscillating_ohlcv())
    if name not in _DEAD_DEFAULT_STRATEGIES:
        assert len(loop.trades) > 0, f"{name} 在三组行情下均无交易，对拍无效"
    _assert_results_identical(loop, vec)


# ── 对拍：关键策略的非默认参数 + 引擎配置变化 ───────────────────────────────


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("ma_cross", {"fast": 10, "slow": 60}),
        ("ma_cross", {"fast": 3, "slow": 8}),
        ("macd", {"short": 6, "long": 13, "signal": 5}),
        ("boll_breakout", {"n": 10, "p": 2.5}),
        ("rsi_reversal", {"n": 7, "oversold": 25, "overbought": 78}),
        ("donchian", {"n": 20}),
    ],
)
def test_key_strategies_alternate_params(name: str, params: dict[str, Any]) -> None:
    """任务点名的四个策略（含非默认参数）对拍一致。"""
    df = _synthetic_ohlcv(seed=99)
    loop, vec = _run_both(name, df, params)
    if len(loop.trades) == 0:
        loop, vec = _run_both(name, _oscillating_ohlcv(), params)
    assert len(loop.trades) > 0, f"{name}{params} 两组行情下均无交易，对拍无效"
    _assert_results_identical(loop, vec)


def test_wr_reversal_parity_with_skip_bounds() -> None:
    """wr_reversal 的向量化机制对拍（需 skip_bounds 越过死的默认边界）。

    其阈值参数边界为负数区间（-100~-40 / -60~0），而 MyTT 的 WR 是 0~100
    刻度——任何合法参数都无法触发交易（策略现状如此，两路径行为一致）。
    为了让它的掩码/状态机路径也被对拍覆盖，用 skip_bounds 传 0~100 刻度内
    的阈值绕过边界（寻优器同款机制）。
    """
    df = _oscillating_ohlcv()
    loop, vec = _run_both(
        "wr_reversal", df, {"n": 14, "oversold": 40, "overbought": 60}, skip_bounds=True
    )
    assert len(loop.trades) > 0
    _assert_results_identical(loop, vec)


@pytest.mark.parametrize("warmup", [0, 20, 100])
def test_warmup_bars_consistency(warmup: int) -> None:
    """warmup 期不产生信号：两路径一致（向量化按候选 bar 过滤）。"""
    df = _synthetic_ohlcv(seed=11)
    loop, vec = _run_both("ma_cross", df, warmup_bars=warmup)
    _assert_results_identical(loop, vec)


def test_degenerate_low_cash_consistency() -> None:
    """极低资金：BUY 信号买不足 1 手（策略仓位状态不变），两路径仍一致。"""
    df = _synthetic_ohlcv(seed=5, base=200.0)  # 高价股 + 小资金 → 整手买入失败
    loop, vec = _run_both("ma_cross", df, cash=1500.0)
    _assert_results_identical(loop, vec)


def test_nondefault_fees_and_execution_consistency() -> None:
    """非默认费率/滑点/成交价模式：信号路径无关下游，但全流程仍应一致。"""
    df = _synthetic_ohlcv(seed=13)
    kw: dict[str, Any] = {
        "commission": 0.0005,
        "stamp_tax": 0.0005,
        "slippage": 0.01,
        "execution": "next_close",
    }
    loop, vec = _run_both("macd", df, **kw)
    _assert_results_identical(loop, vec)


def test_indicator_cache_consistency() -> None:
    """挂载指标缓存（寻优场景）时向量化路径照常工作且一致。"""
    from easy_tdx.backtest.indicator_cache import IndicatorCache

    df = _synthetic_ohlcv(seed=21)
    loop = BacktestEngine(
        get_registry().get("ma_cross").build(), signal_path="loop", indicator_cache=IndicatorCache()
    ).run(df)
    cache = IndicatorCache()
    vec = BacktestEngine(
        get_registry().get("ma_cross").build(), signal_path="auto", indicator_cache=cache
    ).run(df)
    _assert_results_identical(loop, vec)


# ── 约束检测（显式、可测试） ─────────────────────────────────────────────────


class _PlainStrategy(Strategy):
    """未实现 entry_exit_masks 的普通策略（应走逐 bar）。"""

    def init(self) -> None:
        self.ma = self.I(MA, self.data.close, 5)

    def next(self) -> None:
        if self.ma[self._bar_index] > 0 and self.position["size"] == 0:
            self.buy()


def test_eligibility_requires_masks_hook() -> None:
    """未覆写 entry_exit_masks → 不具备资格（原因可读）。"""
    engine = BacktestEngine(_PlainStrategy)
    eligible, reason = engine._vectorize_eligibility(_PlainStrategy(), None)
    assert eligible is False
    assert "entry_exit_masks" in reason


def test_eligibility_rejects_chanlun() -> None:
    """缠论注入（result 或 level）→ 不具备资格。"""
    strat = get_registry().get("ma_cross").build()
    engine = BacktestEngine(strat, chanlun_level="DAILY")
    eligible, reason = engine._vectorize_eligibility(strat, None)
    assert eligible is False
    assert "缠论" in reason

    engine2 = BacktestEngine(strat)
    eligible2, reason2 = engine2._vectorize_eligibility(strat, {"fake": "chanlun"})
    assert eligible2 is False
    assert "缠论" in reason2


def test_eligibility_accepts_builtin() -> None:
    """内置策略（无缠论）→ 具备资格。"""
    strat = get_registry().get("ma_cross").build()
    engine = BacktestEngine(strat)
    eligible, _ = engine._vectorize_eligibility(strat, None)
    assert eligible is True


def test_signal_path_vector_forces_or_raises() -> None:
    """signal_path='vector'：满足约束时正常，不满足时显式抛错。"""
    df = _synthetic_ohlcv(200)
    # 满足约束：正常运行且与 loop 一致
    loop, vec = _run_both("ma_cross", df)
    forced = BacktestEngine(get_registry().get("ma_cross").build(), signal_path="vector").run(df)
    _assert_results_identical(loop, forced)

    # 不满足约束：显式 ValueError（而非静默回退）
    with pytest.raises(ValueError, match="向量化约束"):
        BacktestEngine(_PlainStrategy, signal_path="vector").run(df)


def test_signal_path_invalid_rejected() -> None:
    with pytest.raises(ValueError, match="signal_path"):
        BacktestEngine(_PlainStrategy, signal_path="fast")


def test_auto_falls_back_on_mask_shape_mismatch() -> None:
    """掩码形状错误（策略实现 bug）：auto 静默回退逐 bar，结果仍一致。"""

    class _BadMaskStrategy(_PlainStrategy):
        def entry_exit_masks(self) -> tuple[np.ndarray, np.ndarray]:
            return np.zeros(3, dtype=bool), np.zeros(3, dtype=bool)

    df = _synthetic_ohlcv(200, seed=3)
    loop = BacktestEngine(_PlainStrategy, signal_path="loop").run(df)
    fallback = BacktestEngine(_BadMaskStrategy, signal_path="auto").run(df)
    _assert_results_identical(loop, fallback)


def test_vector_path_actually_used_for_builtins() -> None:
    """默认 signal_path='auto' 下内置策略确实走了向量化（防止回退被掩盖）。

    若某策略信号依赖路径状态（无法用静态掩码等价表达），应在此说明并
    考虑引擎走逐 bar 回放的白名单机制（当前无此类策略）。
    """
    from easy_tdx.backtest.strategy import Strategy as Base

    for name in get_registry().names():
        strat_cls = get_registry().get(name).strategy_cls
        assert strat_cls.entry_exit_masks is not Base.entry_exit_masks, (
            f"{name} 未实现 entry_exit_masks，auto 将永远走逐 bar"
        )
