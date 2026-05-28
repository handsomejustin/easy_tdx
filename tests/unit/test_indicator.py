"""indicator.py 离线单元测试。"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from easy_tdx.indicator import compute_indicators, list_indicators, _REGISTRY


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.5)
    high = close + np.abs(rng.standard_normal(n))
    low = close - np.abs(rng.standard_normal(n))
    open_ = low + (high - low) * rng.random(n)
    vol = (rng.random(n) * 1e6).astype(float)
    return pd.DataFrame({
        "datetime": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": vol * close,
    })


class TestRegistry:
    def test_all_indicators_registered(self):
        assert len(_REGISTRY) >= 22

    def test_list_indicators_returns_metadata(self):
        info = list_indicators()
        assert len(info) >= 22
        for entry in info:
            assert "name" in entry
            assert "inputs" in entry
            assert "outputs" in entry
            assert "description" in entry


class TestComputeIndicators:
    def test_single_indicator_macd(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["MACD"])
        assert "MACD_DIF" in result.columns
        assert "MACD_DEA" in result.columns
        assert "MACD_HIST" in result.columns
        assert len(result) == 200

    def test_multiple_indicators(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["MACD", "KDJ", "RSI"])
        for col in ["MACD_DIF", "MACD_DEA", "MACD_HIST", "KDJ_K", "KDJ_D", "KDJ_J", "RSI"]:
            assert col in result.columns

    def test_keep_ohlcv_true(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["RSI"], keep_ohlcv=True)
        for col in ["open", "high", "low", "close", "vol"]:
            assert col in result.columns

    def test_keep_ohlcv_false(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["RSI"], keep_ohlcv=False)
        assert "close" not in result.columns
        assert "RSI" in result.columns
        # datetime 应保留
        assert "datetime" in result.columns

    def test_keep_ohlcv_false_no_time_cols(self):
        df = _make_ohlcv()
        df = df.drop(columns=["datetime"])
        result = compute_indicators(df, ["RSI"], keep_ohlcv=False)
        assert "close" not in result.columns
        assert "RSI" in result.columns

    def test_tail_parameter(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["MACD"], tail=30)
        assert len(result) == 30
        assert "MACD_DIF" in result.columns

    def test_case_insensitive(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["macd", "kdj"])
        assert "MACD_DIF" in result.columns
        assert "KDJ_K" in result.columns

    def test_custom_params(self):
        df = _make_ohlcv()
        r1 = compute_indicators(df, ["MACD"])
        r2 = compute_indicators(df, ["MACD"], params={"MACD": {"SHORT": 10}})
        # 不同参数应产生不同结果
        assert not np.allclose(r1["MACD_DIF"].values, r2["MACD_DIF"].values, equal_nan=True)

    def test_unknown_indicator_raises(self):
        df = _make_ohlcv()
        with pytest.raises(ValueError, match="未知指标"):
            compute_indicators(df, ["FAKE_INDICATOR"])

    def test_missing_input_columns_raises(self):
        df = pd.DataFrame({"close": np.random.randn(200)})
        with pytest.raises(ValueError, match="缺少必要列"):
            compute_indicators(df, ["KDJ"])

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = compute_indicators(df, ["MACD"])
        assert result.empty

    def test_short_data_warning(self):
        df = _make_ohlcv(50)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compute_indicators(df, ["MACD"])
            assert any("120" in str(warning.message) for warning in w)

    def test_rsi_range(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["RSI"])
        rsi = result["RSI"].dropna()
        assert (rsi >= -10).all() and (rsi <= 110).all()

    def test_boll_bands_order(self):
        df = _make_ohlcv(200)
        result = compute_indicators(df, ["BOLL"])
        valid = result.dropna(subset=["BOLL_UPPER", "BOLL_LOWER"])
        assert (valid["BOLL_UPPER"] >= valid["BOLL_LOWER"]).all()

    def test_obv_with_volume(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["OBV"])
        assert "OBV" in result.columns

    def test_brar_needs_open(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["BRAR"])
        assert "AR" in result.columns
        assert "BR" in result.columns

    def test_all_registered_indicators_run(self):
        """确保所有注册的指标都能无错运行。"""
        df = _make_ohlcv(250)
        for name in _REGISTRY:
            result = compute_indicators(df, [name])
            spec = _REGISTRY[name]
            for col in spec.outputs:
                assert col in result.columns, f"{name} missing output {col}"

    def test_result_index_reset(self):
        df = _make_ohlcv()
        result = compute_indicators(df, ["RSI"])
        assert list(result.index) == list(range(len(result)))
