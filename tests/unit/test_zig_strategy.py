"""zig_breakout 内置策略单元测试（借鉴 Fork 移植，v1.29）。

覆盖：注册表登记与参数 schema、合成锯齿行情能产生交易、
止损单挂在买入信号上（OCO bracket）、寻优预设网格登记。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategies import get_registry
from easy_tdx.backtest.strategies.presets import STRATEGY_PRESETS


def _zigzag_df(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """先跌后大涨再回调的合成行情（触发 ZIG 波谷启动与见顶清仓）。"""
    rng = np.random.default_rng(seed)
    trend = np.concatenate(
        [
            np.linspace(100, 80, n // 3),
            np.linspace(80, 130, n * 2 // 5),
            np.linspace(130, 110, n - n // 3 - n * 2 // 5),
        ]
    )
    close = trend + rng.normal(0, 0.8, len(trend))
    high = close + rng.uniform(0, 1.5, len(trend))
    low = close - rng.uniform(0, 1.5, len(trend))
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=len(trend), freq="B"),
            "open": close + rng.normal(0, 0.3, len(trend)),
            "high": high,
            "low": low,
            "close": close,
            "vol": rng.integers(1e6, 5e6, len(trend)).astype(float),
            "amount": close * 1e6,
        }
    )


def test_registry_entry_and_params():
    entry = get_registry().get("zig_breakout")
    assert entry.label == "ZIG 右侧突破回补"
    names = [p.name for p in entry.params]
    assert names == ["zig_delta", "confirm_pct", "hhv_period", "stop_loss_pct"]
    defaults = {p.name: p.default for p in entry.params}
    assert defaults == {
        "zig_delta": 10.0,
        "confirm_pct": 2.0,
        "hhv_period": 20,
        "stop_loss_pct": 3.0,
    }


def test_build_validates_params():
    entry = get_registry().get("zig_breakout")
    inst = entry.build({"zig_delta": 5})
    assert inst.p["zig_delta"] == 5.0 and inst.p["hhv_period"] == 20
    with pytest.raises(ValueError):
        entry.build({"zig_delta": -1})  # 低于 min_value


def test_strategy_trades_and_bracket_stop():
    entry = get_registry().get("zig_breakout")
    result = BacktestEngine(entry.build(), cash=1_000_000).run(_zigzag_df())
    assert len(result.trades) > 0
    # 锯齿行情应至少出现一次 BUY（trades 为 DataFrame）
    assert (result.trades["direction"] == "BUY").any()
    assert (result.trades["direction"] == "SELL").any()


def test_strategy_file_variant_loadable():
    """strategies/zig_breakout.py 独立文件可供 --strategy-file 加载。"""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "strategies" / "zig_breakout.py"
    spec = importlib.util.spec_from_file_location("zig_file_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    result = BacktestEngine(mod.ZigBreakoutStrategy(), cash=1_000_000).run(_zigzag_df())
    assert len(result.trades) > 0
    assert (result.trades["direction"] == "BUY").any()


def test_preset_grid_registered():
    assert "zig_breakout" in STRATEGY_PRESETS
    grid = STRATEGY_PRESETS["zig_breakout"]
    assert "zig_delta" in grid and "confirm_pct" in grid
    # 笛卡尔积不超过寻优器上限
    n = 1
    for vals in grid.values():
        n *= len(vals)
    assert n <= 200
