"""扩展市场路由：期货、港股、美股等扩展市场行情数据（MAC 协议）。

实现说明：Web 曾用 ex 扩展协议客户端（AsyncExTdxClient，0x122B 系列），但该协议
数据源对美股等市场支持不全（TSLA 等请求超时）；CLI 的 easy-tdx ex 命令一直走
MacExClient（MAC 协议，端口 7727）且实测可用，故此处统一改用 AsyncMacExClient，
与 CLI 行为保持一致。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import category_from_str, ex_market_from_str, period_times_from_category
from easy_tdx.web.deps import get_ex_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["ex-market"])


def _df_resp(df: Any) -> DataFrameResponse:
    """DataFrame → DataFrameResponse（处理 datetime / numpy 标量）。"""
    return DataFrameResponse.from_dataframe(df)


@router.get("/ex/bars", response_model=DataFrameResponse)
async def ex_bars(
    market: str = Query(..., description="扩展市场代码，如 US_STOCK / HK_MAIN_BOARD 或数字"),
    code: str = Query(..., description="证券代码（如 TSLA / 00700）"),
    category: str = Query(
        "DAY", description="K线周期: MIN_1/MIN_5/MIN_15/MIN_30/MIN_60/DAY/WEEK/MONTH"
    ),
    start: int = Query(0, ge=0),
    count: int = Query(700, ge=1, le=800),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场 K 线数据（MAC 协议，支持美股/港股/期货）。"""
    period = period_times_from_category(category_from_str(category))[0]
    df = await client.goods_kline(
        market=ex_market_from_str(market),
        code=code,
        period=period,
        start=start,
        count=count,
    )
    return _df_resp(df)


@router.get("/ex/quote", response_model=DataFrameResponse)
async def ex_quote(
    market: str = Query(..., description="扩展市场代码"),
    code: str = Query(..., description="证券代码"),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场实时报价。"""
    df = await client.goods_quotes([(ex_market_from_str(market), code)])
    return _df_resp(df)


@router.get("/ex/minute", response_model=DataFrameResponse)
async def ex_minute(
    market: str = Query(..., description="扩展市场代码"),
    code: str = Query(..., description="证券代码"),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场分时数据（当日，每分钟一行）。"""
    df = await client.goods_tick_chart(market=ex_market_from_str(market), code=code)
    return _df_resp(df)


@router.get("/ex/transaction", response_model=DataFrameResponse)
async def ex_transaction(
    market: str = Query(..., description="扩展市场代码"),
    code: str = Query(..., description="证券代码"),
    start: int = Query(0, ge=0),
    count: int = Query(1800, ge=1, le=3000),
    client: Any = Depends(get_ex_client),
) -> DataFrameResponse:
    """获取扩展市场逐笔成交数据（start=0 为最新一笔，倒序）。"""
    df = await client.goods_transaction(
        market=ex_market_from_str(market), code=code, start=start, count=count
    )
    return _df_resp(df)
