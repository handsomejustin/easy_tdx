"""品种感知费率模型测试（fees.py + 引擎 auto_fees 集成）。

覆盖：
- 品种推断：沪深股票 / ETF / LOF / 可转债 / B 股 / 指数 / 北交所
- 费率解析：ETF/债券免印花税、B 股印花税保留、最低佣金差异
- 引擎集成：auto_fees 覆盖默认费率、显式费率优先、关闭时行为不变
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.fees import (
    InstrumentKind,
    detect_instrument_kind,
    resolve_fee_model,
)
from easy_tdx.backtest.strategy import Strategy

# --------------------------------------------------------------------------- #
# 品种推断
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("symbol", "market", "expected"),
    [
        ("600519", "SH", InstrumentKind.STOCK),  # 贵州茅台
        ("601398", "SH", InstrumentKind.STOCK),  # 工商银行
        ("000001", "SZ", InstrumentKind.STOCK),  # 平安银行
        ("300750", "SZ", InstrumentKind.STOCK),  # 宁德时代（创业板）
        ("688981", "SH", InstrumentKind.STOCK),  # 中芯国际（科创板）
        ("832000", "BJ", InstrumentKind.STOCK),  # 北交所
        ("510300", "SH", InstrumentKind.ETF),  # 沪深300ETF
        ("588000", "SH", InstrumentKind.ETF),  # 科创50ETF
        ("159915", "SZ", InstrumentKind.ETF),  # 创业板ETF
        ("501018", "SH", InstrumentKind.LOF),  # 南方原油 LOF
        ("160632", "SZ", InstrumentKind.LOF),  # 深 LOF
        ("113050", "SH", InstrumentKind.BOND),  # 沪可转债
        ("123456", "SZ", InstrumentKind.BOND),  # 深可转债
        ("900901", "SH", InstrumentKind.B_SHARE),  # 沪 B
        ("200002", "SZ", InstrumentKind.B_SHARE),  # 深 B
        ("000001", "SH", InstrumentKind.INDEX),  # 上证指数（同码不同市！）
        ("399001", "SZ", InstrumentKind.INDEX),  # 深证成指
        ("SH:510300", None, InstrumentKind.ETF),  # 带前缀 symbol
        ("SZ:159915", None, InstrumentKind.ETF),
        ("510300", 1, InstrumentKind.ETF),  # 通达信 int 市场
        ("000001", 0, InstrumentKind.STOCK),
        ("510300", None, InstrumentKind.ETF),  # 无市场，仅代码粗判
        ("600519", None, InstrumentKind.STOCK),
    ],
)
def test_detect_instrument_kind(symbol, market, expected):
    assert detect_instrument_kind(symbol, market) == expected


def test_detect_kind_case_insensitive_and_spacing():
    assert detect_instrument_kind(" sh:510300 ") == InstrumentKind.ETF
    assert detect_instrument_kind("sh510300") == InstrumentKind.ETF


# --------------------------------------------------------------------------- #
# 费率解析
# --------------------------------------------------------------------------- #


def test_stock_fees_keep_stamp_tax():
    fee = resolve_fee_model("SH:600519")
    assert fee.kind is InstrumentKind.STOCK
    assert fee.stamp_tax == pytest.approx(0.001)
    assert fee.commission == pytest.approx(0.0003)
    assert fee.min_commission == pytest.approx(5.0)


def test_etf_fees_exempt_stamp_tax():
    """核心法定差异：ETF 免印花税。"""
    fee = resolve_fee_model("SH:510300")
    assert fee.kind is InstrumentKind.ETF
    assert fee.stamp_tax == 0.0


def test_bond_fees_exempt_stamp_tax_and_lower_min():
    fee = resolve_fee_model("SZ:123456")
    assert fee.kind is InstrumentKind.BOND
    assert fee.stamp_tax == 0.0
    assert fee.min_commission < 5.0


def test_b_share_fees_keep_stamp_tax():
    fee = resolve_fee_model("SH:900901")
    assert fee.kind is InstrumentKind.B_SHARE
    assert fee.stamp_tax == pytest.approx(0.001)


def test_fee_model_frozen():
    fee = resolve_fee_model("SH:510300")
    with pytest.raises(AttributeError):
        fee.commission = 0.0  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 引擎集成
# --------------------------------------------------------------------------- #


class _AlwaysBuy(Strategy):
    """首根 K 线全仓买入、持有到末尾的极简策略（保证产生 BUY 交易）。"""

    def init(self) -> None:
        self._bought = False

    def next(self) -> None:
        if not self._bought:
            self.buy()
            self._bought = True


def _df(n: int = 50) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = 10.0 + np.linspace(0, 2, n)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "vol": [1000.0] * n,
        }
    )


def test_engine_auto_fees_overrides_stamp_tax_for_etf():
    """auto_fees=True 时 ETF 不收印花税（对比股票默认收）。"""
    # 股票（默认费率，stamp_tax=0.001）
    eng_stock = BacktestEngine(_AlwaysBuy, cash=100000.0)
    assert eng_stock._stamp_tax == pytest.approx(0.001)

    # ETF + auto_fees → stamp_tax 归零
    eng_etf = BacktestEngine(_AlwaysBuy, cash=100000.0, symbol="SH:510300", auto_fees=True)
    assert eng_etf._stamp_tax == 0.0
    assert eng_etf._commission == pytest.approx(0.0003)

    # 结果 config 里带 symbol 与解析后的费率
    result = eng_etf.run(_df())
    assert result.config["symbol"] == "SH:510300"
    assert result.config["stamp_tax"] == 0.0
    assert result.config["min_commission"] == pytest.approx(5.0)


def test_engine_explicit_fees_win_over_auto():
    """显式传入非默认费率时，auto_fees 不覆盖用户意图。"""
    eng = BacktestEngine(
        _AlwaysBuy,
        cash=100000.0,
        commission=0.0001,
        min_commission=1.0,
        stamp_tax=0.0005,
        symbol="SH:510300",
        auto_fees=True,
    )
    assert eng._commission == pytest.approx(0.0001)
    assert eng._min_commission == pytest.approx(1.0)
    assert eng._stamp_tax == pytest.approx(0.0005)


def test_engine_auto_fees_without_symbol_is_noop():
    """auto_fees=True 但没给 symbol → 保持默认（不报错）。"""
    eng = BacktestEngine(_AlwaysBuy, cash=100000.0, auto_fees=True)
    assert eng._commission == pytest.approx(0.0003)
    assert eng._stamp_tax == pytest.approx(0.001)


def test_engine_default_behavior_unchanged():
    """不传新参数时行为与旧版完全一致（向后兼容）。"""
    eng = BacktestEngine(_AlwaysBuy, cash=100000.0)
    assert eng._commission == pytest.approx(0.0003)
    assert eng._min_commission == pytest.approx(5.0)
    assert eng._stamp_tax == pytest.approx(0.001)
    assert eng._symbol is None


def test_portfolio_engine_auto_fees_per_symbol():
    """组合引擎按各标的逐只解析费率（股票收印花税、ETF 不收）。"""
    from easy_tdx.backtest.portfolio_engine import PortfolioBacktestEngine, StockData

    df = _df(60)
    stocks = [
        StockData(code="600519", market="SH", df=df),
        StockData(code="510300", market="SH", df=df),
    ]
    engine = PortfolioBacktestEngine(
        strategy=_AlwaysBuy,
        stocks=stocks,
        total_cash=200000.0,
        auto_fees=True,
    )
    result = engine.run()
    # 两只标的结果的 config 中费率不同
    stock_cfg = result.individual_results["SH600519"].config
    etf_cfg = result.individual_results["SH510300"].config
    assert stock_cfg["stamp_tax"] == pytest.approx(0.001)
    assert etf_cfg["stamp_tax"] == 0.0
