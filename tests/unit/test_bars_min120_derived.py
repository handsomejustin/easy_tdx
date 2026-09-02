"""120 分钟 K 线重采样与逐 bar 衍生字段单元测试（bars.py 纯函数，v1.29）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.web.routers.bars import (
    _MIN_120_ALIASES,
    _attach_derived,
    _resample_pairs,
)


def _minute_df(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-02 10:30", periods=n, freq="60min"),
            "open": [10, 11, 12, 13, 14][:n],
            "close": [10.5, 11.5, 12.5, 13.5, 14.5][:n],
            "high": [10.8, 11.9, 12.9, 13.9, 14.9][:n],
            "low": [9.9, 10.9, 11.9, 12.9, 13.9][:n],
            "vol": [100, 200, 300, 400, 500][:n],
            "amount": [1000, 2000, 3000, 4000, 5000][:n],
        }
    )


class TestResamplePairs:
    def test_odd_count_drops_oldest(self):
        """奇数根丢最旧一根，保最新数据两两对齐。"""
        r = _resample_pairs(_minute_df(5), 10)
        assert len(r) == 2
        row = r.iloc[0]  # 原 bar1+bar2
        assert row["open"] == 11 and row["close"] == 12.5
        assert row["high"] == 12.9 and row["low"] == 10.9  # max/min
        assert row["vol"] == 500 and row["amount"] == 5000  # sum
        assert str(row["datetime"]) == "2024-01-02 12:30:00"  # 后一根时间

    def test_even_count_keeps_all(self):
        r = _resample_pairs(_minute_df(4), 10)
        assert len(r) == 2
        assert r.iloc[0]["open"] == 10  # 从 bar0 起

    def test_count_trims_oldest_side(self):
        r = _resample_pairs(_minute_df(4), 1)
        assert len(r) == 1 and r.iloc[0]["close"] == 13.5  # tail 保留

    def test_empty_passthrough(self):
        assert _resample_pairs(pd.DataFrame(), 10).empty
        assert _resample_pairs(None, 10) is None  # type: ignore[arg-type]

    def test_missing_optional_columns(self):
        df = _minute_df(4).drop(columns=["amount"])
        r = _resample_pairs(df, 10)
        assert "amount" not in r.columns and len(r) == 2


class TestAttachDerived:
    def test_basic_fields(self):
        d = _attach_derived(_minute_df(3))
        assert {"pre_close", "change", "change_pct", "amplitude_pct"} <= set(d.columns)
        assert d.iloc[0]["pre_close"] == 10  # 首根 = 本根开盘
        assert d.iloc[0]["change"] == 0.5 and d.iloc[0]["change_pct"] == 5.0
        assert d.iloc[1]["pre_close"] == 10.5
        assert d.iloc[1]["change_pct"] == round((11.5 / 10.5 - 1) * 100, 4)
        assert abs(d.iloc[0]["amplitude_pct"] - (10.8 - 9.9) / 10 * 100) < 1e-6

    def test_nonpositive_preclose_floor(self):
        """QFQ 复权后前收为 0/负时按 0.01 兜底，不产生 inf。"""
        df = _minute_df(3)
        df.loc[0, "close"] = -5.0
        d = _attach_derived(df)
        assert np.isfinite(d["change_pct"]).all()
        assert d.iloc[1]["change_pct"] == round((11.5 / 0.01 - 1) * 100, 4)

    def test_empty_and_missing_close(self):
        assert _attach_derived(pd.DataFrame()).empty
        df = pd.DataFrame({"open": [1.0]})
        assert "pre_close" not in _attach_derived(df).columns


def test_min_120_aliases():
    assert _MIN_120_ALIASES == {"MIN_120", "120M", "120MIN"}
