
from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# 组合/多标的：扩展市场与加密货币符号支持（组合回测页扩展）
# ---------------------------------------------------------------------------


def test_portfolio_schema_accepts_ex_and_crypto_symbols() -> None:
    """stocks 支持 A 股 / 扩展市场 / 加密混合（组合回测页扩展）。"""
    from easy_tdx.web.backtest_schemas import PortfolioBacktestRequest

    req = PortfolioBacktestRequest(
        strategy="ma_cross",
        stocks=[
            "SZ:000001",
            "SH:600519",
            "US_STOCK:TSLA",
            "HK_MAIN_BOARD:00700",
            "CFFEX_FUTURES:IFL0",
            "CRYPTO:BTCUSDT",
        ],
    )
    assert len(req.stocks) == 6


def test_portfolio_schema_rejects_bad_symbols() -> None:
    """非法标的格式仍被拒绝。"""
    from pydantic import ValidationError

    from easy_tdx.web.backtest_schemas import PortfolioBacktestRequest

    with pytest.raises(ValidationError):
        PortfolioBacktestRequest(strategy="ma_cross", stocks=["garbage"])

    with pytest.raises(ValidationError):
        PortfolioBacktestRequest(strategy="ma_cross", stocks=["SZ:000001,SH:600519"])


def test_single_symbol_schema_accepts_ex_and_crypto() -> None:
    """单标的 symbol 校验同步放宽（US_STOCK:TSLA / CRYPTO:BTCUSDT）。"""
    from easy_tdx.web.backtest_schemas import BacktestRequest, OptimizeBacktestRequest

    assert BacktestRequest(strategy="ma_cross", symbol="US_STOCK:TSLA").symbol == "US_STOCK:TSLA"
    assert BacktestRequest(strategy="ma_cross", symbol="CRYPTO:BTCUSDT").symbol == "CRYPTO:BTCUSDT"
    opt = OptimizeBacktestRequest(
        strategy="ma_cross", param_grid={"fast": [5]}, symbol="CFFEX_FUTURES:IFL0"
    )
    assert opt.symbol == "CFFEX_FUTURES:IFL0"


def test_crypto_price_scale() -> None:
    """高价加密标的等比缩放价格，比率不变。"""
    from easy_tdx.web.routers.backtest import _crypto_price_scale

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=3),
            "open": [65000.0, 66000.0, 67000.0],
            "high": [66000.0, 67000.0, 68000.0],
            "low": [64000.0, 65000.0, 66000.0],
            "close": [65500.0, 66500.0, 67500.0],
            "vol": [100.0, 200.0, 300.0],
            "amount": [6.5e8, 1.3e9, 2.0e9],
        }
    )
    out = _crypto_price_scale(df)
    # 67500 → 5 位 → ÷100
    assert out.iloc[-1]["close"] == pytest.approx(675.0)
    assert out.iloc[0]["close"] == pytest.approx(655.0)
    # 量与额不变
    assert out.iloc[0]["vol"] == 100.0
    assert out.iloc[0]["amount"] == pytest.approx(6.5e8)

    # 低价标的（如 1.5 元）不缩放
    df2 = pd.DataFrame(
        {"datetime": pd.date_range("2026-01-01", periods=2), "open": [1.5, 1.6], "high": [1.6, 1.7],
         "low": [1.4, 1.5], "close": [1.55, 1.65], "vol": [1.0, 2.0], "amount": [3.0, 4.0]}
    )
    out2 = _crypto_price_scale(df2)
    assert out2.iloc[-1]["close"] == pytest.approx(1.65)


class _FakeTdxClient:
    """模拟 A 股取数（get_security_bars）。"""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    async def get_security_bars(self, market, code, category, start, count) -> pd.DataFrame:
        if start > 0:
            return pd.DataFrame()
        return self._df


def _fake_request(ex_client: Any | None = None) -> Any:
    """构造带 app.state.ex_client 的假 Request。"""
    class _State:
        def __init__(self) -> None:
            self.ex_client = ex_client

    class _App:
        def __init__(self) -> None:
            self.state = _State()

    class _Req:
        def __init__(self) -> None:
            self.app = _App()

    return _Req()


async def test_fetch_bars_for_symbol_ashare(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 股符号走 TdxClient 取数 + 日期过滤。"""
    from easy_tdx.web.routers.backtest import _fetch_bars_for_symbol

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2025-01-01", periods=5),
            "open": [10.0] * 5,
            "high": [11.0] * 5,
            "low": [9.0] * 5,
            "close": [10.5] * 5,
            "vol": [1000.0] * 5,
            "amount": [10500.0] * 5,
        }
    )
    out = await _fetch_bars_for_symbol(
        _fake_request(),
        _FakeTdxClient(df),
        "SZ:000001",
        "DAY",
        800,
        "2025-01-03",
        None,
    )
    assert out is not None
    assert len(out) >= 3
    assert str(out.iloc[0]["datetime"])[:10] >= "2025-01-03"


async def test_fetch_bars_for_symbol_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    """CRYPTO 符号走 Binance + 自动价格缩放。"""
    import easy_tdx.crypto as crypto_mod
    import easy_tdx.web.routers.backtest as mod

    df = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-01-01", periods=3),
            "open": [65000.0, 66000.0, 67000.0],
            "high": [66000.0, 67000.0, 68000.0],
            "low": [64000.0, 65000.0, 66000.0],
            "close": [65500.0, 66500.0, 67500.0],
            "vol": [100.0, 200.0, 300.0],
            "amount": [6.5e8, 1.3e9, 2.0e9],
        }
    )

    captured: dict = {}

    class _FakeCryptoClient:
        async def klines(self, symbol, interval, limit):
            captured["symbol"] = symbol
            captured["interval"] = interval
            return df

    monkeypatch.setattr(crypto_mod, "AsyncCryptoClient", _FakeCryptoClient)

    out = await mod._fetch_bars_for_symbol(
        _fake_request(), _FakeTdxClient(pd.DataFrame()), "CRYPTO:BTCUSDT", "DAY", 800
    )
    assert captured["symbol"] == "BTCUSDT"
    assert captured["interval"] == "1d"
    assert out is not None
    assert out.iloc[-1]["close"] == pytest.approx(675.0)  # 已缩放


async def test_fetch_bars_for_symbol_ex_market() -> None:
    """ex 市场符号走 AsyncMacExClient.goods_kline。"""
    from easy_tdx.web.routers.backtest import _fetch_bars_for_symbol

    captured: dict = {}

    class _FakeExClient:
        async def goods_kline(self, market, code, period, start, count):
            captured["market"] = market
            captured["code"] = code
            df = pd.DataFrame(
                {
                    "datetime": pd.date_range("2026-01-01", periods=3),
                    "open": [4600.0, 4610.0, 4620.0],
                    "high": [4630.0] * 3,
                    "low": [4590.0] * 3,
                    "close": [4615.0, 4620.0, 4610.0],
                    "vol": [100.0] * 3,
                    "amount": [4.6e5] * 3,
                }
            )
            return df

    out = await _fetch_bars_for_symbol(
        _fake_request(_FakeExClient()),
        _FakeTdxClient(pd.DataFrame()),
        "CFFEX_FUTURES:IFL0",
        "DAY",
        800,
    )
    assert captured["market"] == 47  # CFFEX_FUTURES
    assert captured["code"] == "IFL0"
    assert out is not None and len(out) == 3


async def test_fetch_bars_for_symbol_ex_disabled_raises() -> None:
    """serve 未启用 --enable-ex 时 ex 符号报清晰错误。"""
    from easy_tdx.web.routers.backtest import _fetch_bars_for_symbol

    with pytest.raises(ValueError, match="enable-ex"):
        await _fetch_bars_for_symbol(
            _fake_request(None),
            _FakeTdxClient(pd.DataFrame()),
            "US_STOCK:TSLA",
            "DAY",
            800,
        )
