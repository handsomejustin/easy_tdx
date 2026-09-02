"""中金所成交持仓排名路由（独立数据源，不依赖 TDX 服务器）。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(tags=["ccpm"])

_PRODUCT_PATTERN = r"^(IF|IH|IC|IM|TS|TF|T|TL)$"
_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class CcpmProductsResponse(BaseModel):
    """品种列表 + 科普元数据（静态）。"""

    products: list[dict[str, str]]
    count: int


class CcpmRankResponse(BaseModel):
    """成交持仓排名（宽表：合约 × 排名 对齐三类排名）。"""

    trading_day: str  # 实际交易日 YYYYMMDD（自动回溯时可能 ≠ 请求日期）
    product: str
    product_name: str
    data: list[dict[str, Any]]
    count: int


@router.get("/ccpm/products", response_model=CcpmProductsResponse)
async def ccpm_products() -> CcpmProductsResponse:
    """全部可采集品种与科普元数据（品种代码 / 标的 / 合约规模 / 一句话介绍）。"""
    from easy_tdx.ccpm import list_products

    products = list_products()
    return CcpmProductsResponse(products=products, count=len(products))


@router.get("/ccpm/rank", response_model=CcpmRankResponse)
async def ccpm_rank(
    product: str = Query("IF", pattern=_PRODUCT_PATTERN, description="品种代码"),
    date: str | None = Query(
        None,
        pattern=_DATE_PATTERN,
        description="交易日 YYYY-MM-DD；缺省自动回溯最近有数据的交易日",
    ),
    refresh: bool = Query(False, description="忽略本地缓存强制重新抓取"),
) -> CcpmRankResponse:
    """获取某品种某交易日的成交持仓排名（官网每日收盘后约 16:15 发布）。

    每行 = 某合约某排名，成交量 / 持买单量（多单）/ 持卖单量（空单）三类
    前 20 名会员并排对齐；包含该品种当日全部挂牌合约。
    """
    from easy_tdx.ccpm import CcpmClient, CcpmError, CcpmNoDataError, normalize_product

    client = CcpmClient()

    def _fetch() -> CcpmRankResponse:
        try:
            df = (
                client.get_rank(product, date, refresh=refresh)
                if date
                else client.latest_rank(product, refresh=refresh)
            )
        except CcpmNoDataError as e:
            raise HTTPException(
                status_code=404,
                detail=f"{product} 在 {date} 无数据：该日期非交易日或数据尚未发布"
                "（每个交易日收盘后约 16:15 生成）",
            ) from e
        except CcpmError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        meta = normalize_product(product)
        records = df.to_dict(orient="records")
        trading_day = str(records[0]["trading_day"]) if records else (date or "").replace("-", "")
        return CcpmRankResponse(
            trading_day=trading_day,
            product=meta.code,
            product_name=meta.name,
            data=records,
            count=len(records),
        )

    return await asyncio.to_thread(_fetch)
