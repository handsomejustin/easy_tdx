"""MAC 行情路由：排行行情列表、竞价数据、异动行情。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import (
    category_mac_from_str,
    filter_types_from_str,
    market_value_from_str,
    sort_order_from_str,
    sort_type_from_str,
)
from easy_tdx.web.deps import get_mac_client
from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["mac-quotes"])


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/mac/quote-list", response_model=DataFrameResponse)
async def quote_list(
    category: str = Query("A", description="市场分类: A/SH/SZ/KCB/BJ/CYB"),
    start: int = Query(0, ge=0, description="分页起始位置"),
    count: int = Query(80, ge=1, le=5000, description="返回数量"),
    sort_type: str = Query("CHANGE_PCT", description="排序字段"),
    sort_order: str = Query("DESC", description="排序方向: ASC/DESC"),
    exclude: str | None = Query(None, description="过滤标志（逗号分隔）: ST,KC,BJ,..."),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取分排行行情列表（涨幅/成交量/换手等排序）。"""
    exclude_flags = filter_types_from_str(exclude) if exclude else None
    df = await client.get_stock_quotes_list(
        category=category_mac_from_str(category),
        start=start,
        count=count,
        sort_type=sort_type_from_str(sort_type),
        sort_order=sort_order_from_str(sort_order),
        exclude_flags=exclude_flags,
    )
    return _df_resp(df)


@router.get("/mac/auction", response_model=DataFrameResponse)
async def auction(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取集合竞价数据。"""
    df = await client.get_auction(market=market_value_from_str(market), code=code)
    return _df_resp(df)
