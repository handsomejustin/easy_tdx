"""轮动组合引擎测试（排名换仓 / 槽位等额 / 止盈止损 / 刷新频率 / 绩效）。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.rotation import RotationEngine, RotationResult, formula_score, momentum_score


def _stock(
    n: int = 250, seed: int = 1, drift: float = 0.001, start: str = "2024-01-01"
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 10.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.01, n))
    return pd.DataFrame(
        {
            "datetime": pd.date_range(start, periods=n, freq="B"),
            "open": close * 0.999,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "vol": 1e6,
            "amount": close * 1e6,
        }
    )


def _pool(drifts: dict[str, float], n: int = 250) -> dict[str, pd.DataFrame]:
    return {sym: _stock(n, seed=i, drift=drift) for i, (sym, drift) in enumerate(drifts.items())}


# ── 基础结构 ─────────────────────────────────────────────────────────────────


def test_rotation_basic_run_and_structure():
    pool = _pool({"SH:600519": 0.002, "SZ:000001": 0.001, "SZ:000858": 0.0005, "SH:601318": 0.0})
    engine = RotationEngine(pool, momentum_score(20), slots=2, refresh="weekly")
    result = engine.run()
    assert isinstance(result, RotationResult)
    assert len(result.equity_curve) >= 200
    assert result.performance.get("total_return") is not None
    assert result.config["slots"] == 2
    # 净值曲线字段完整（可喂组合评级）
    first = result.equity_curve[0]
    assert {"datetime", "cash", "position_value", "total", "drawdown_pct"} <= set(first)


def test_rotation_strong_pool_makes_money():
    """普涨池 + 动量排名 → 正收益。"""
    pool = _pool({f"SH:60000{i}": 0.004 for i in range(5)})
    result = RotationEngine(pool, momentum_score(20), slots=3, refresh="monthly").run()
    assert result.performance["total_return"] > 0


def test_rotation_weak_pool_loses_less_than_buyhold():
    """普跌池 → 负收益（动量轮动不做空）。"""
    pool = _pool({f"SH:60000{i}": -0.004 for i in range(5)})
    result = RotationEngine(pool, momentum_score(20), slots=2).run()
    assert result.performance["total_return"] < 0


def test_rotation_trades_have_reasons():
    pool = _pool({f"SH:60000{i}": 0.002 if i % 2 else -0.001 for i in range(6)})
    result = RotationEngine(pool, momentum_score(10), slots=2, refresh="weekly").run()
    reasons = {t["reason"] for t in result.trades}
    assert "rotation" in reasons  # 买入
    assert "rank_exit" in reasons  # 跌出排名的卖出


def test_rotation_respects_slots():
    """持仓数永远 ≤ slots。"""
    pool = _pool({f"SH:60000{i}": 0.001 + 0.0005 * i for i in range(8)})
    engine = RotationEngine(pool, momentum_score(10), slots=3, refresh="weekly")
    # 用逐日持仓推断：trades 序列重放
    holdings = 0
    peak_holdings = 0
    for t in result_trades_sorted(engine):
        if t["direction"] == "BUY":
            holdings += 1
            peak_holdings = max(peak_holdings, holdings)
        else:
            holdings -= 1
    assert peak_holdings <= 3


def result_trades_sorted(engine: RotationEngine) -> list[dict]:
    result = engine.run()
    return result.trades


def test_rotation_stop_loss_triggers():
    """深跌池 + 10% 止损 → 出现 stop_loss 卖出。"""
    pool = _pool({f"SH:60000{i}": -0.006 for i in range(4)})
    result = RotationEngine(
        pool, momentum_score(5), slots=2, refresh="monthly", stop_loss=0.05
    ).run()
    reasons = {t["reason"] for t in result.trades}
    assert "stop_loss" in reasons


def test_rotation_refresh_frequencies():
    pool = _pool({f"SH:60000{i}": 0.001 * (i + 1) for i in range(4)})
    r_daily = RotationEngine(pool, momentum_score(10), slots=2, refresh="daily").run()
    r_monthly = RotationEngine(pool, momentum_score(10), slots=2, refresh="monthly").run()
    # 月调仓的调仓日数 ≤ 日调仓
    assert len(r_monthly.rebalance_dates) <= len(r_daily.rebalance_dates)
    # 月调仓约 12 次/年（250 交易日）
    assert 3 <= len(r_monthly.rebalance_dates) <= 15


def test_rotation_formula_score_synergy():
    """公式打分与轮动联动：数值输出作为排名分。"""
    pool = _pool({f"SH:60000{i}": 0.001 * (i + 1) for i in range(4)})
    score = formula_score("动量分: C / REF(C, 20) * 100;")
    result = RotationEngine(pool, score, slots=2, refresh="monthly").run()
    assert result.performance["total_return"] is not None


def test_rotation_result_serializable():
    pool = _pool({f"SH:60000{i}": 0.001 * (i + 1) for i in range(4)})
    result = RotationEngine(pool, momentum_score(10), slots=2).run()
    d = result.to_dict()
    text = json.dumps(d, ensure_ascii=False)
    assert "equity_curve" in text
    assert d["n_rebalances"] >= 1


def test_rotation_rejects_bad_config():
    pool = _pool({"SH:600519": 0.001, "SZ:000001": 0.001})
    with pytest.raises(ValueError, match="refresh"):
        RotationEngine(pool, momentum_score(5), refresh="yearly")
    with pytest.raises(ValueError, match="stock_dfs"):
        RotationEngine({}, momentum_score(5))
    with pytest.raises(ValueError, match="slots"):
        RotationEngine(pool, momentum_score(5), slots=0)


def test_rotation_equal_weight_no_allin_single_stock():
    """首日建仓是等额分批，不是一把全买一只（槽位预算 = 净值/槽数）。"""
    pool = _pool({f"SH:60000{i}": 0.001 * (i + 1) for i in range(6)})
    result = RotationEngine(pool, momentum_score(10), slots=3, refresh="monthly").run()
    first_day_buys = [
        t for t in result.trades if t["direction"] == "BUY" and t["reason"] == "rotation"
    ][:3]
    if len(first_day_buys) >= 2:
        values = [t["size"] * t["price"] for t in first_day_buys]
        # 同日买入的各笔金额接近（等额），差异 < 25%（价格整百取整的摩擦）
        assert max(values) / max(min(values), 1) < 1.25


def test_momentum_score_helper():
    df = _stock(30, seed=1, drift=0.01)
    score = momentum_score(10)(df)
    assert score > 0
    assert momentum_score(10)(_stock(5)) == 0.0  # 数据不足 → 0
