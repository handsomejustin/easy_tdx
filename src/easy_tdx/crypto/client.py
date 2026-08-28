"""easy_tdx.crypto — Binance 加密货币行情客户端（免费公共 API，无需 Key）。

数据源: https://api.binance.com/api/v3
  - /klines          → OHLCV K 线（现货）
  - /ticker/price    → 最新价
  - /ping            → 连通性

零第三方依赖（stdlib urllib）。代理：显式 proxy 参数优先，其次 https_proxy 环境变量。

K 线响应（Binance klines 12 列）映射为 DataFrame 列：
  datetime(bar 开始时间，UTC 无时区) / open / high / low / close / vol / amount(报价资产成交额)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from urllib import parse
from urllib import request as urlrequest

import pandas as pd

from ..exceptions import TdxError

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.binance.com"
_UA = "Mozilla/5.0 easy-tdx crypto client"

# 支持的 K 线周期（Binance interval 原样透传）
VALID_INTERVALS = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
)

MAX_LIMIT = 1000


class CryptoError(TdxError):
    """加密货币数据源错误。"""


def normalize_symbol(symbol: str) -> str:
    """交易对归一化：btc/usdt、BTC-USDT、btcusdt 均转为 BTCUSDT。"""
    s = symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")
    if not s or ("USDT" not in s and len(s) < 5):
        raise CryptoError(f"交易对格式异常: {symbol!r}（如 BTCUSDT）")
    return s


def _resolve_proxy(proxy: str | None) -> dict[str, str] | None:
    """显式 proxy 优先，其次 https_proxy / HTTPS_PROXY 环境变量。"""
    p = proxy or os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if not p:
        return None
    if "://" not in p:
        p = "http://" + p
    return {"https": p, "http": p}


class CryptoClient:
    """同步 Binance 加密货币行情客户端（现货）。

    用法::

        from easy_tdx.crypto import CryptoClient

        c = CryptoClient()
        df = c.klines("BTCUSDT", interval="1d", limit=300)
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        timeout: float = 15.0,
        proxy: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._proxy = proxy

    def ping(self) -> bool:
        """连通性检查（/api/v3/ping）。"""
        try:
            self._get("/api/v3/ping", {})
            return True
        except CryptoError:
            return False

    def klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 500,
    ) -> pd.DataFrame:
        """获取 K 线（OHLCV）。

        Args:
            symbol: 交易对（如 BTCUSDT，兼容 btc/usdt、BTC-USDT 写法）。
            interval: Binance 周期（1m/5m/15m/30m/1h/4h/1d/1w/1M 等）。
            limit: 返回条数（1..1000）。

        Returns:
            DataFrame[datetime, open, high, low, close, vol, amount]
        """
        sym = normalize_symbol(symbol)
        if interval not in VALID_INTERVALS:
            raise CryptoError(f"不支持的周期 {interval!r}，可选: {sorted(VALID_INTERVALS)}")
        if not 1 <= limit <= MAX_LIMIT:
            raise CryptoError(f"limit 需在 1..{MAX_LIMIT}")
        rows = self._get("/api/v3/klines", {"symbol": sym, "interval": interval, "limit": limit})
        if not isinstance(rows, list):
            raise CryptoError(f"klines 响应异常: {rows!r}")
        if not rows:
            return pd.DataFrame(
                columns=["datetime", "open", "high", "low", "close", "vol", "amount"]
            )
        df = pd.DataFrame(
            [
                {
                    "datetime": pd.Timestamp(int(r[0]), unit="ms", tz="UTC").tz_localize(None),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "vol": float(r[5]),
                    "amount": float(r[7]),  # quoteAssetVolume（如 USDT 计）
                }
                for r in rows
            ]
        )
        return df

    def ticker_price(self, symbol: str) -> float:
        """获取最新成交价。"""
        sym = normalize_symbol(symbol)
        data = self._get("/api/v3/ticker/price", {"symbol": sym})
        try:
            return float(data["price"])
        except (KeyError, TypeError, ValueError):
            raise CryptoError(f"ticker/price 响应异常: {data!r}") from None

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        """GET JSON。参数 urlencode；代理走 ProxyHandler；错误统一转 CryptoError。"""
        url = self._base_url + path + "?" + parse.urlencode(params)
        req = urlrequest.Request(url, headers={"User-Agent": _UA})
        proxies = _resolve_proxy(self._proxy)
        opener = (
            urlrequest.build_opener(urlrequest.ProxyHandler(proxies))
            if proxies
            else urlrequest.build_opener()
        )
        try:
            with opener.open(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urlrequest.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise CryptoError(f"Binance API {e.code}: {body[:200]}") from None
        except OSError as e:
            raise CryptoError(f"Binance API 网络错误: {e}") from None


class AsyncCryptoClient:
    """异步包装：asyncio.to_thread 复用同步实现，零额外依赖。

    用法::

        from easy_tdx.crypto import AsyncCryptoClient

        async def main():
            c = AsyncCryptoClient()
            df = await c.klines("BTCUSDT", interval="1d", limit=300)
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        timeout: float = 15.0,
        proxy: str | None = None,
    ) -> None:
        self._sync = CryptoClient(base_url, timeout, proxy)

    async def ping(self) -> bool:
        return await asyncio.to_thread(self._sync.ping)

    async def klines(
        self,
        symbol: str,
        interval: str = "1d",
        limit: int = 500,
    ) -> pd.DataFrame:
        return await asyncio.to_thread(self._sync.klines, symbol, interval, limit)

    async def ticker_price(self, symbol: str) -> float:
        return await asyncio.to_thread(self._sync.ticker_price, symbol)
