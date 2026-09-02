"""黄金测试（golden tests）：回测引擎指标快照回归（v1.28 新增）。

借鉴 akquant 的 golden 测试机制：把「内置策略在固定随机种子合成数据上的
全部绩效指标」与「交易规则场景（止损/止盈/移动止损/OCO/费率）的成交明细」
锁定为 JSON 基线（``tests/golden/backtest_metrics.json``），每次引擎改动后
跑一遍比对——撮合、费率、信号时序任何静默漂移都会在这里爆出来。

生成/更新基线::

    EASY_TDX_REGEN_GOLDEN=1 python -m pytest tests/unit/test_golden_backtest.py

比对容差：rel=1e-6 / abs=1e-6——紧到能抓住费率或成交时点级别的逻辑漂移
（通常引起 >0.001 的变动），松到容忍跨平台浮点求和顺序的尾数噪声。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.benchmark import (
    compute_benchmark_comparison,
    run_buy_hold_benchmark,
)
from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategies import builtin  # noqa: F401  # 触发注册
from easy_tdx.backtest.strategies.registry import _REGISTRY
from easy_tdx.backtest.strategy import Strategy

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "golden" / "backtest_metrics.json"
REGEN = os.environ.get("EASY_TDX_REGEN_GOLDEN", "") == "1"

# 与基线 meta 一致的固定参数
SEED = 20260902
BARS = 400
CASH = 100000.0

# 内置策略锁定的指标子集（全部为确定性数值；int 与 float 分开比对）
STRATEGY_METRICS_FLOAT = (
    "total_return",
    "max_drawdown",
    "sharpe",
    "win_rate",
    "ulcer_index",
    "var_95",
    "cvar_95",
    "sqn",
)
STRATEGY_METRICS_INT = (
    "total_trades",
    "max_consecutive_wins",
    "max_consecutive_losses",
)


def _golden_df() -> pd.DataFrame:
    """固定种子的合成日线（几何随机游走 + 温和上行漂移）。"""
    rng = np.random.default_rng(SEED)
    close = 20.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.018, BARS)))
    high = close * (1 + np.abs(rng.normal(0, 0.008, BARS)))
    low = close * (1 - np.abs(rng.normal(0, 0.008, BARS)))
    open_ = low + (high - low) * rng.uniform(0, 1, BARS)
    vol = rng.uniform(5e5, 5e6, BARS)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2023-01-02", periods=BARS, freq="B"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": close * vol,
        }
    )


# ── 规则场景策略（手工构造行情路径，锁定触发语义本身） ───────────────────────


class _BuyOnce(Strategy):
    """首根买入（可携带 bracket 参数），不再主动交易；无参数时即买入持有。"""

    def __init__(self, **bracket: Any) -> None:
        super().__init__()
        self._bracket: dict[str, Any] = bracket
        self._bought = False

    def init(self) -> None:
        pass

    def next(self) -> None:
        if not self._bought:
            self.buy(**self._bracket)
            self._bought = True


def _rule_df(closes: list[float]) -> pd.DataFrame:
    """按收盘价序列构造无随机因素的 OHLC（high/low = close ±1%）。"""
    arr = np.asarray(closes, dtype=float)
    n = len(arr)
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": arr,
            "high": arr * 1.01,
            "low": arr * 0.99,
            "close": arr,
            "vol": [1000.0] * n,
            "amount": arr * 1000,
        }
    )


def _run_rule(closes: list[float], **bracket: Any) -> dict[str, Any]:
    """跑规则场景，返回待锁定的摘要（成交明细 + 关键指标）。"""
    result = BacktestEngine(_BuyOnce(**bracket), cash=CASH).run(_rule_df(closes))
    trades = [
        [t.direction, round(float(t.price), 4), int(pd.Timestamp(t.datetime).strftime("%Y%m%d"))]
        for t in result.trades.itertuples()
        if not t.rejected
    ]
    return {
        "trades": trades,
        "total_return": float(result.performance["total_return"]),
        "total_trades": int(result.performance["total_trades"]),
    }


RULE_SCENARIOS: dict[str, dict[str, Any]] = {
    # 跌破固定止损 9.5 → 触发 SELL@9.5，延迟下一根成交
    "stop_loss": {
        "closes": [10, 10.2, 10.1, 9.8, 9.3, 9.0, 8.8, 8.6, 8.4, 8.2],
        "bracket": {"stop_loss": 9.5},
    },
    # 触及固定止盈 11.0 → OCO 使止损线失效
    "take_profit": {
        "closes": [10, 10.3, 10.8, 11.2, 11.5, 11.8, 12.0, 12.2, 12.4, 12.6],
        "bracket": {"stop_loss": 9.0, "take_profit": 11.0},
    },
    # 自最高收盘 12 回撤 8% → 11.04 触发移动止损
    "trailing_stop": {
        "closes": [10, 10.2, 10.5, 11, 11.5, 12, 11.9, 11.5, 11.0, 10.5, 10.0, 9.5],
        "bracket": {"trail_stop": 0.08},
    },
    # 百分比 bracket：5% 止损 / 10% 止盈（基准价 = 信号根收盘 10）
    "bracket_pct": {
        "closes": [10, 10.3, 10.8, 11.2, 11.5, 11.8, 12.0, 12.2, 12.4, 12.6],
        "bracket": {"stop_loss_pct": 0.05, "take_profit_pct": 0.10},
    },
}


def _build_golden() -> dict[str, Any]:
    """重新计算并返回完整黄金基线。"""
    df = _golden_df()

    strategies: dict[str, dict[str, Any]] = {}
    for name in sorted(_REGISTRY.names()):
        reg = _REGISTRY.get(name)
        cls = reg.strategy_cls
        perf = BacktestEngine(cls, cash=CASH).run(df).performance
        entry: dict[str, Any] = {k: float(perf[k]) for k in STRATEGY_METRICS_FLOAT}
        entry.update({k: int(perf[k]) for k in STRATEGY_METRICS_INT})
        strategies[name] = entry

    rules = {
        key: _run_rule(spec["closes"], **spec["bracket"]) for key, spec in RULE_SCENARIOS.items()
    }

    # 买入持有基准 + CAPM 对比（用 ma_cross 做策略侧）
    bh = run_buy_hold_benchmark(df, cash=CASH)
    ma = _REGISTRY.get("ma_cross").strategy_cls
    ma_result = BacktestEngine(ma, cash=CASH).run(df)
    comparison = compute_benchmark_comparison(
        ma_result.equity_curve,
        BacktestEngine(_BuyOnce(), cash=CASH).run(df).equity_curve,
    )

    return {
        "meta": {
            "seed": SEED,
            "bars": BARS,
            "cash": CASH,
            "tolerance": {"rel": 1e-6, "abs": 1e-6},
            "note": "regen: EASY_TDX_REGEN_GOLDEN=1 pytest tests/unit/test_golden_backtest.py",
        },
        "strategies": strategies,
        "rules": rules,
        "buy_hold": {k: float(v) for k, v in bh.items()},
        "benchmark_comparison": {k: float(v) for k, v in comparison.items()},
    }


def _load_golden() -> dict[str, Any]:
    if not GOLDEN_PATH.exists():
        pytest.fail(
            f"黄金基线缺失: {GOLDEN_PATH}\n"
            "首次生成请运行: EASY_TDX_REGEN_GOLDEN=1 python -m pytest "
            "tests/unit/test_golden_backtest.py"
        )
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _save_golden(data: dict[str, Any]) -> None:
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    """加载基线；REGEN=1 时重新计算并写盘后返回。"""
    if REGEN:
        data = _build_golden()
        _save_golden(data)
        return data
    return _load_golden()


def _assert_metric(actual: Any, expected: Any, label: str) -> None:
    """int 精确比对；float 按 rel=abs=1e-6 容差比对。"""
    if isinstance(expected, int) and not isinstance(expected, bool):
        assert actual == expected, f"{label}: {actual} != {expected}"
    else:
        assert float(actual) == pytest.approx(float(expected), rel=1e-6, abs=1e-6), (
            f"{label}: {actual} != {expected}"
        )


# ── 测试入口 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(_REGISTRY.names()))
def test_golden_builtin_strategies(golden: dict[str, Any], name: str) -> None:
    """全部内置策略在固定数据上的绩效指标与基线一致。"""
    perf = BacktestEngine(_REGISTRY.get(name).strategy_cls, cash=CASH).run(_golden_df()).performance
    baseline = golden["strategies"][name]
    for key in STRATEGY_METRICS_FLOAT:
        _assert_metric(perf[key], baseline[key], f"{name}.{key}")
    for key in STRATEGY_METRICS_INT:
        _assert_metric(perf[key], baseline[key], f"{name}.{key}")


@pytest.mark.parametrize("scenario", sorted(RULE_SCENARIOS))
def test_golden_rule_scenarios(golden: dict[str, Any], scenario: str) -> None:
    """止损/止盈/移动止损/OCO 触发语义（成交价与时点）与基线一致。"""
    spec = RULE_SCENARIOS[scenario]
    actual = _run_rule(spec["closes"], **spec["bracket"])
    baseline = golden["rules"][scenario]
    assert actual["total_trades"] == baseline["total_trades"], scenario
    assert len(actual["trades"]) == len(baseline["trades"]), f"{scenario}: 成交笔数漂移"
    for i, (a, b) in enumerate(zip(actual["trades"], baseline["trades"])):
        assert a[0] == b[0], f"{scenario} 第{i}笔方向漂移: {a} vs {b}"
        _assert_metric(a[1], b[1], f"{scenario}.trades[{i}].price")
        assert a[2] == b[2], f"{scenario} 第{i}笔成交日漂移: {a} vs {b}"
    _assert_metric(actual["total_return"], baseline["total_return"], f"{scenario}.total_return")


def test_golden_buy_hold(golden: dict[str, Any]) -> None:
    """买入持有基准指标与基线一致。"""
    bh = run_buy_hold_benchmark(_golden_df(), cash=CASH)
    for key, expected in golden["buy_hold"].items():
        _assert_metric(bh[key], expected, f"buy_hold.{key}")


def test_golden_benchmark_comparison(golden: dict[str, Any]) -> None:
    """Alpha/Beta/IR/TE 基准对比指标与基线一致。"""
    df = _golden_df()
    ma = _REGISTRY.get("ma_cross").strategy_cls
    strategy_curve = BacktestEngine(ma, cash=CASH).run(df).equity_curve
    bh_curve = BacktestEngine(_BuyOnce(), cash=CASH).run(df).equity_curve
    comparison = compute_benchmark_comparison(strategy_curve, bh_curve)
    for key, expected in golden["benchmark_comparison"].items():
        _assert_metric(comparison[key], expected, f"benchmark.{key}")


def test_golden_meta_frozen(golden: dict[str, Any]) -> None:
    """基线 meta 与测试常量一致（防止改数据参数后忘记重建基线）。"""
    meta = golden["meta"]
    assert meta["seed"] == SEED
    assert meta["bars"] == BARS
    assert meta["cash"] == CASH
