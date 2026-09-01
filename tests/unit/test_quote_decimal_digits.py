"""报价小数位推断（Issue #8 + 看板指数 ×0.1 修复）的语义锁定测试。"""

from __future__ import annotations

import pytest

from easy_tdx.commands.security_quotes import _price_decimal_digits
from easy_tdx.models.enums import Market


@pytest.mark.parametrize(
    ("market", "code", "expected", "why"),
    [
        # ── 大盘指数：点位恒两位小数（科创50 1647.53），原始单位是「分」 ──
        (Market.SH, "000001", 2, "上证指数"),
        (Market.SH, "000300", 2, "沪深300（实测 4611.44，按 3 位曾缩成 461.144）"),
        (Market.SH, "000688", 2, "科创50（实测 1647.53，按 3 位曾缩成 164.753）"),
        (Market.SH, "000905", 2, "中证500"),
        (Market.SH, "000016", 2, "上证50"),
        (Market.SZ, "399001", 2, "深证成指（深市指数走默认分支，一直正确）"),
        (Market.SZ, "399006", 2, "创业板指"),
        # ── 统计指数：字段是计数语义（price×10 还原家数），必须保持 3 位 ──
        (Market.SH, "880005", 3, "全市场行情统计（market_stat 依赖）"),
        (Market.SH, "880006", 3, "涨跌停统计"),
        # ── 板块指数：与大盘指数同口径，两位小数 ──
        (Market.SH, "881106", 2, "行业板块指数（种植业，实测 1039.93）"),
        (Market.SH, "885418", 2, "概念板块指数"),
        # ── 基金/ETF：真实三位小数（Issue #8）──
        (Market.SH, "510300", 3, "沪深300ETF（价格如 4.611）"),
        (Market.SH, "588000", 3, "科创50ETF"),
        (Market.SZ, "159915", 3, "创业板ETF"),
        # ── 股票：两位 ──
        (Market.SH, "600519", 2, "主板"),
        (Market.SH, "688981", 2, "科创板"),
        (Market.SZ, "000001", 2, "深市 000 开头是股票（平安银行），与 SH000001 同码不同义"),
        (Market.SZ, "300750", 2, "创业板"),
        (Market.BJ, "920002", 2, "北交所"),
    ],
)
def test_price_decimal_digits(market: Market, code: str, expected: int, why: str) -> None:
    assert _price_decimal_digits(market, code) == expected, why
