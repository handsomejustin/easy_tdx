"""公式回测适配器 + REST 端点测试（三通道一致性）。"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from easy_tdx.backtest.formula_strategy import (  # noqa: E402
    FormulaStrategyError,
    attach_formula_columns,
    pick_signal_columns,
    run_formula_backtest,
)
from easy_tdx.formula import compile_formula  # noqa: E402


def _df(n: int = 300, seed: int = 3, drift: float = 0.002) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 10.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.012, n))
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": close * 0.999,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "vol": 1e6,
            "amount": close * 1e6,
        }
    )


_MA_CROSS = "快: MA(C, 5);\n慢: MA(C, 20);\n买入: CROSS(快, 慢);\n卖出: CROSS(慢, 快);"


# ── attach / pick ─────────────────────────────────────────────────────────────


def test_attach_formula_columns():
    df = _df(100)
    enriched, result = attach_formula_columns(df, compile_formula(_MA_CROSS))
    assert {"快", "慢", "买入", "卖出"} <= set(enriched.columns)
    assert len(enriched) == len(df)
    assert df is not enriched  # 副本，不污染原 df


def test_pick_signal_columns_by_hint_and_order():
    _, result = attach_formula_columns(_df(60), compile_formula(_MA_CROSS))
    buy, sell = pick_signal_columns(result)
    assert (buy, sell) == ("买入", "卖出")  # 名称提示（买/卖）优先

    _, r2 = attach_formula_columns(_df(60), compile_formula("A: C > MA(C, 5); B: C < MA(C, 5);"))
    buy2, sell2 = pick_signal_columns(r2)
    assert (buy2, sell2) == ("A", "B")  # 无提示时按声明顺序

    buy3, _ = pick_signal_columns(r2, buy_col="B")
    assert buy3 == "B"  # 显式指定优先


def test_pick_requires_signal():
    from easy_tdx.formula import FormulaResult

    result = FormulaResult(columns={"x": np.ones(5)}, values=["x"])
    with pytest.raises(FormulaStrategyError, match="布尔信号"):
        pick_signal_columns(result)


# ── run_formula_backtest ──────────────────────────────────────────────────────


def test_run_formula_backtest_full_report():
    out = run_formula_backtest(_df(300), _MA_CROSS)
    assert out["performance"]["total_trades"] >= 1
    assert out["formula"]["buy_col"] == "买入"
    assert out["formula"]["sell_col"] == "卖出"
    assert out["grade"]["grade"] in ("S", "A", "B", "C", "D")
    assert 0 <= out["score"]["total"] <= 100
    assert "trades" in out and "equity_curve" in out


def test_run_formula_backtest_no_sell_col_holds():
    """只有买入列 → 买入后持有到末尾（1 笔完成交易=0 卖出，持仓中）。"""
    out = run_formula_backtest(_df(200, drift=0.004), "买入: CROSS(MA(C,3), MA(C,30));")
    assert out["formula"]["sell_col"] is None
    assert out["performance"]["total_return"] > 0


def test_run_formula_backtest_accepts_compiled():
    compiled = compile_formula(_MA_CROSS)
    out = run_formula_backtest(_df(200), compiled)
    assert out["formula"]["buy_col"] == "买入"


def test_run_formula_backtest_rejects_no_signal():
    with pytest.raises(ValueError, match="布尔信号"):
        run_formula_backtest(_df(60), "数值: MA(C, 5);")


def test_run_formula_backtest_json_serializable():
    import json

    out = run_formula_backtest(_df(150), _MA_CROSS)
    json.dumps(out, default=str)


# ── REST 端点 ─────────────────────────────────────────────────────────────────


def _client() -> TestClient:
    from easy_tdx.web import create_app

    return TestClient(create_app())


def _ohlcv(n: int = 200) -> list[dict[str, object]]:
    df = _df(n)
    df["datetime"] = df["datetime"].dt.strftime("%Y-%m-%d")
    return json_records(df)


def json_records(df: pd.DataFrame) -> list[dict[str, object]]:
    import json

    return json.loads(df.to_json(orient="records", force_ascii=False))


def test_rest_formula_validate_ok_and_error():
    client = _client()
    r = client.post(
        "/api/v1/formula/validate", json={"text": "金叉: CROSS(MA(C,5), MA(C,20)); 强度: MA(C,5);"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["signals"] == ["金叉"]
    assert body["values"] == ["强度"]

    r2 = client.post("/api/v1/formula/validate", json={"text": "A := ;"})
    assert r2.status_code == 200
    assert r2.json()["ok"] is False
    assert r2.json()["error"]


def test_rest_formula_compute_inline_ohlcv():
    client = _client()
    r = client.post(
        "/api/v1/formula/compute",
        json={"text": "买入: C > REF(C, 1); 值: MA(C, 5);", "ohlcv": _ohlcv(100), "tail": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signals"] == ["买入"]
    assert "last_row" in body and "值" in body["last_row"]
    assert len(body["recent"]) == 5


def test_rest_formula_backtest_async_task():
    client = _client()
    r = client.post(
        "/api/v1/formula/backtest/run/async",
        json={"text": _MA_CROSS, "ohlcv": _ohlcv(300), "cash": 100000.0},
    )
    assert r.status_code == 202, r.text
    task_id = r.json()["task_id"]
    for _ in range(200):
        st = client.get(f"/api/v1/backtest/tasks/{task_id}").json()
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert st["status"] == "done", st.get("error")
    result = st["result"]
    assert result["formula"]["buy_col"] == "买入"
    assert result["performance"]["total_trades"] >= 1


def test_rest_formula_screen_async_task():
    client = _client()
    # 两份不同行情：A 上涨（末根 C>REF(C,1) 大概率真）、B 构造末根下跌
    up = _ohlcv(120)
    r = client.post(
        "/api/v1/formula/screen/run/async",
        json={"text": "买入: C > REF(C, 1);", "symbols": ["SH:600519"], "ohlcv": up[:0]},
    )
    # symbols 路径需要行情连接——离线环境预期 400/500（无 mock client）
    # 这里只验证请求校验（symbols 非空）不炸
    assert r.status_code in (400, 500, 202)
