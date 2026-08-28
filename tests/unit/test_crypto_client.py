"""Binance 加密货币模块离线测试 —— mock HTTP，零网络依赖。

覆盖：交易对归一化、klines 解析（12 列 → DataFrame）、周期/limit 校验、
ticker_price 解析、错误转换、异步客户端。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from easy_tdx.crypto import CryptoClient
from easy_tdx.crypto.client import CryptoError, normalize_symbol

# ---------------------------------------------------------------------------
# 交易对归一化
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BTCUSDT", "BTCUSDT"),
        ("btcusdt", "BTCUSDT"),
        ("BTC/USDT", "BTCUSDT"),
        ("btc-usdt", "BTCUSDT"),
        (" ETH_USDT ", "ETHUSDT"),
    ],
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


def test_normalize_symbol_empty_raises() -> None:
    with pytest.raises(CryptoError):
        normalize_symbol("")


# ---------------------------------------------------------------------------
# klines 解析
# ---------------------------------------------------------------------------


def _fake_klines_rows(n: int = 3) -> list[list[str]]:
    """构造 Binance klines 12 列响应（与真实响应同构）。"""
    rows = []
    for i in range(n):
        t = 1_700_000_000_000 + i * 86_400_000  # 每日一根
        rows.append(
            [
                str(t),
                f"{100 + i:.2f}",  # open
                f"{101 + i:.2f}",  # high
                f"{99 + i:.2f}",  # low
                f"{100.5 + i:.2f}",  # close
                f"{1000 + i:.2f}",  # volume
                str(t + 86_399_999),  # closeTime
                f"{200000 + i:.2f}",  # quoteAssetVolume → amount
                "100",  # trades
                f"{500 + i}.0",  # taker base
                f"{100000 + i}.0",  # taker quote
                "0",
            ]
        )
    return rows


def test_klines_parses_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """12 列响应 → datetime/open/high/low/close/vol/amount。"""
    client = CryptoClient()
    monkeypatch.setattr(client, "_get", lambda path, params: _fake_klines_rows(3))

    df = client.klines("BTCUSDT", interval="1d", limit=3)

    assert list(df.columns) == ["datetime", "open", "high", "low", "close", "vol", "amount"]
    assert len(df) == 3
    assert df.iloc[0]["open"] == pytest.approx(100.0)
    assert df.iloc[0]["close"] == pytest.approx(100.5)
    assert df.iloc[0]["vol"] == pytest.approx(1000.0)
    assert df.iloc[0]["amount"] == pytest.approx(200000.0)
    # datetime 为 UTC 无时区 Timestamp
    ts = pd.Timestamp(df.iloc[0]["datetime"])
    assert ts == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc).replace(tzinfo=None)


def test_klines_invalid_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """不支持的周期直接抛 CryptoError，不发请求。"""
    client = CryptoClient()

    with pytest.raises(CryptoError, match="周期"):
        client.klines("BTCUSDT", interval="2x", limit=3)


def test_klines_limit_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """limit 越界抛 CryptoError。"""
    client = CryptoClient()

    with pytest.raises(CryptoError, match="limit"):
        client.klines("BTCUSDT", interval="1d", limit=0)

    with pytest.raises(CryptoError, match="limit"):
        client.klines("BTCUSDT", interval="1d", limit=1001)


# ---------------------------------------------------------------------------
# ticker_price
# ---------------------------------------------------------------------------


def test_ticker_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """最新价解析。"""
    client = CryptoClient()
    monkeypatch.setattr(
        client, "_get", lambda path, params: {"symbol": "BTCUSDT", "price": "65432.10"}
    )

    assert client.ticker_price("BTCUSDT") == pytest.approx(65432.10)


def test_ticker_price_bad_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """响应缺 price 字段 → CryptoError。"""
    client = CryptoClient()
    monkeypatch.setattr(client, "_get", lambda path, params: {"error": "x"})

    with pytest.raises(CryptoError):
        client.ticker_price("BTCUSDT")


# ---------------------------------------------------------------------------
# 错误转换与 ping
# ---------------------------------------------------------------------------


def test_http_error_becomes_crypto_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 4xx/5xx（如交易对不存在 400）→ CryptoError（走真实 _get 转换）。"""
    import io
    from urllib.error import HTTPError

    import easy_tdx.crypto.client as mod

    class FakeOpener:
        def open(self, req, timeout=None):
            raise HTTPError(
                req.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"code":-1121,"msg":"Invalid symbol."}'),
            )

    monkeypatch.setattr(mod.urlrequest, "build_opener", lambda *a, **k: FakeOpener())
    client = CryptoClient()

    with pytest.raises(CryptoError, match="400"):
        client.klines("BTCUSDT")


def test_ping_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ping 在出错时返回 False 而非抛异常。"""
    client = CryptoClient()

    def boom(path, params):
        raise CryptoError("网络错误")

    monkeypatch.setattr(client, "_get", boom)
    assert client.ping() is False


# ---------------------------------------------------------------------------
# 异步客户端
# ---------------------------------------------------------------------------


async def test_async_klines(monkeypatch: pytest.MonkeyPatch) -> None:
    """异步客户端复用同步实现。"""
    from easy_tdx.crypto import AsyncCryptoClient

    client = AsyncCryptoClient()
    monkeypatch.setattr(client._sync, "_get", lambda path, params: _fake_klines_rows(2))

    df = await client.klines("btc/usdt", interval="1d", limit=2)

    assert len(df) == 2
    assert df.iloc[-1]["close"] == pytest.approx(101.5)


async def test_async_ticker_price(monkeypatch: pytest.MonkeyPatch) -> None:
    from easy_tdx.crypto import AsyncCryptoClient

    client = AsyncCryptoClient()
    monkeypatch.setattr(
        client._sync, "_get", lambda path, params: {"symbol": "BTCUSDT", "price": "1.5"}
    )

    assert await client.ticker_price("BTCUSDT") == pytest.approx(1.5)
