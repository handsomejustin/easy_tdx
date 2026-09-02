"""K 线 vol 字段语义修正回归测试（issue #64）。

背景（2026-09-02 逐字节拆包 + 新浪实时行情/东方财富交叉验证）：
通达信服务端 K 线记录第一个 4 字节字段（f1）的语义随周期/品种变化：
  - 指数分钟线：f1 ≈ amount/100（成交额百元），真实分钟成交量不在报文中；
  - 指数与个股的周/月/季/年线（cat 5/6/10/11）：f1 = 真实成交量/100；
  - 日线（cat 4）与 cat 9（"日线变体"，枚举名误标 YEAR）：f1 = 真实成交量。
解析层据此修正：指数分钟线 vol=NaN，周月季年 ×100，其余原样。
"""

import math
import struct

from easy_tdx.codec.price import put_price
from easy_tdx.codec.volume import _decode_volume
from easy_tdx.commands.security_bars import GetIndexBarsCmd, GetSecurityBarsCmd
from easy_tdx.models.enums import KlineCategory, Market

# 实抓报文中的两个 4 字节字段原始值（2026-09-02 上证指数 5min 15:00 bar）
_IVOL_F1 = 0x4D4713FE  # 解码 ≈ 208,748,512（协议里实为 amount/100）
_IVOL_F2 = 0x509B87A0  # 解码 ≈ 20,874,854,400（真实成交额，元）

# 分钟级时间戳 2026-09-02 15:00（zipday=45958, tminutes=900）
_ZIPDAY, _TMIN = 45958, 900


def _make_body(cat: int, n_bars: int = 1, index: bool = True) -> bytes:
    """构造 n_bars 条 K 线响应报文（OHLC 差分取小值，不影响 vol 断言）。"""
    if cat in (0, 1, 2, 3, 7, 8):
        dt = struct.pack("<HH", _ZIPDAY, _TMIN)
    else:
        dt = struct.pack("<I", 20260902)
    rec = (
        dt
        + put_price(100)
        + put_price(50)
        + put_price(80)
        + put_price(-40)
        + struct.pack("<I", _IVOL_F1)
        + struct.pack("<I", _IVOL_F2)
    )
    if index:
        rec += struct.pack("<HH", 535, 1782)  # 上涨/下跌家数
    return struct.pack("<H", n_bars) + rec * n_bars


class TestIndexBarsVol:
    """GetIndexBarsCmd vol 语义。"""

    def test_minute_vol_is_nan(self):
        """指数分钟线：协议不提供成交量，vol=NaN 而非成交额/100。"""
        for cat in (0, 1, 2, 3, 7, 8):
            cmd = GetIndexBarsCmd(Market.SH, "000001", KlineCategory(cat), 0, 1)
            bars = cmd.parse_response(_make_body(cat))
            assert len(bars) == 1
            assert math.isnan(bars[0].vol), f"cat={cat} 分钟线 vol 应为 NaN"
            assert bars[0].amount == _decode_volume(_IVOL_F2)

    def test_week_plus_vol_restored_x100(self):
        """指数周/月/季/年线：vol ×100 还原为真实成交量(手)。"""
        for cat in (5, 6, 10, 11):
            cmd = GetIndexBarsCmd(Market.SH, "000001", KlineCategory(cat), 0, 1)
            bars = cmd.parse_response(_make_body(cat))
            assert bars[0].vol == _decode_volume(_IVOL_F1) * 100.0, f"cat={cat}"

    def test_daily_and_daily_alt_vol_unchanged(self):
        """指数日线(4)与日线变体(9)：vol 原样（cat 9 虽枚举名 YEAR，实为日线）。"""
        for cat in (4, 9):
            cmd = GetIndexBarsCmd(Market.SH, "000001", KlineCategory(cat), 0, 1)
            bars = cmd.parse_response(_make_body(cat))
            assert bars[0].vol == _decode_volume(_IVOL_F1), f"cat={cat}"

    def test_minute_multi_bar_alignment(self):
        """多条分钟记录解析不错位（涨跌家数 4 字节跳过逻辑完好）。"""
        cmd = GetIndexBarsCmd(Market.SH, "000001", KlineCategory.MIN_5, 0, 2)
        bars = cmd.parse_response(_make_body(0, n_bars=2))
        assert len(bars) == 2
        assert all(math.isnan(b.vol) for b in bars)
        assert bars[0].hour == 15 and bars[0].minute == 0


class TestSecurityBarsVol:
    """GetSecurityBarsCmd vol 语义。"""

    def test_minute_and_daily_vol_unchanged(self):
        """股票分钟/日线：vol 原样（成交量，股）。"""
        for cat in (0, 4, 7):
            cmd = GetSecurityBarsCmd(Market.SH, "600000", KlineCategory(cat), 0, 1)
            bars = cmd.parse_response(_make_body(cat, index=False))
            assert bars[0].vol == _decode_volume(_IVOL_F1), f"cat={cat}"

    def test_week_plus_vol_restored_x100(self):
        """股票周/月/季/年线：vol ×100 还原为股（与日线单位一致）。"""
        for cat in (5, 6, 10, 11):
            cmd = GetSecurityBarsCmd(Market.SH, "600000", KlineCategory(cat), 0, 1)
            bars = cmd.parse_response(_make_body(cat, index=False))
            assert bars[0].vol == _decode_volume(_IVOL_F1) * 100.0, f"cat={cat}"


class TestDataFrameResponseNan:
    """NaN → null：Web 层不得向 Starlette（allow_nan=False）透传 NaN。"""

    def test_nan_serialized_as_none(self):
        import pandas as pd

        from easy_tdx.web.schemas import DataFrameResponse

        df = pd.DataFrame({"vol": [float("nan"), 1.0], "amount": [2.0, 3.0]})
        resp = DataFrameResponse.from_dataframe(df)
        assert resp.data[0]["vol"] is None
        assert resp.data[1]["vol"] == 1.0
        assert resp.count == 2
