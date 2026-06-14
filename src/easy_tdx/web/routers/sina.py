"""新浪财报三表路由（独立数据源，不依赖 TDX 服务器）。"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from easy_tdx.web.schemas import DataFrameResponse

router = APIRouter(tags=["sina"])


@router.get("/sina/financial-report", response_model=DataFrameResponse)
async def financial_report(
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    type: str = Query(
        "lrb",
        pattern=r"^(lrb|fzb|llb)$",
        description="报表类型: lrb(利润表)/fzb(资产负债表)/llb(现金流量表)",
    ),
    num: int = Query(8, ge=1, le=40, description="取最近 N 期"),
) -> DataFrameResponse:
    """获取财报三表（新浪数据源，独立于 TDX 行情服务器）。

    返回每行一期报告（最新在前），列为科目名 + ``{科目}_同比``（如有同比）。
    """
    from easy_tdx.sina import SinaClient, SinaError

    client = SinaClient()

    def _fetch() -> DataFrameResponse:
        df = client.get_financial_report(code, report_type=type, num=num)
        return DataFrameResponse.from_dataframe(df)

    try:
        return await asyncio.to_thread(_fetch)
    except SinaError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
