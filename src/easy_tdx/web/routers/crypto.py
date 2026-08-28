"""加密货币路由（Binance 现货公共 API，无连接生命周期，按请求实例化）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from easy_tdx.crypto import AsyncCryptoClient
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["crypto"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/crypto/bars", response_model=DataFrameResponse)
async def crypto_bars(
    symbol: str = Query(..., description="交易对，如 BTCUSDT（兼容 btc/usdt 写法）"),
    interval: str = Query("1d", description="周期: 1m/5m/15m/30m/1h/4h/1d/1w/1M 等"),
    limit: int = Query(700, ge=1, le=1000, description="K线数量"),
) -> DataFrameResponse:
    """获取加密货币 K 线（OHLCV，datetime/open/high/low/close/vol/amount）。"""
    df = await AsyncCryptoClient().klines(symbol, interval=interval, limit=limit)
    return _df_resp(df)


@router.get("/crypto/price")
async def crypto_price(
    symbol: str = Query(..., description="交易对，如 BTCUSDT"),
) -> dict[str, Any]:
    """获取加密货币最新价。"""
    from easy_tdx.crypto.client import normalize_symbol

    sym = normalize_symbol(symbol)
    price = await AsyncCryptoClient().ticker_price(sym)
    return {"symbol": sym, "price": price}
