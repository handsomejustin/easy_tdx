"""Pydantic request/response schemas for the Web API."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums — mirror easy_tdx.models.enums but as string-based for REST clarity
# ---------------------------------------------------------------------------


class MarketEnum(IntEnum):
    """Market identifier."""

    SZ = 0
    SH = 1
    BJ = 2


class KlineCategoryEnum(IntEnum):
    """K-line period."""

    MIN_5 = 0
    MIN_15 = 1
    MIN_30 = 2
    MIN_60 = 3
    DAY = 4
    WEEK = 5
    MONTH = 6
    MIN_1 = 7
    YEAR = 9
    SEASON = 10


class AdjustEnum(IntEnum):
    """Adjustment type (前复权/后复权)."""

    NONE = 0
    QFQ = 1  # 前复权
    HFQ = 2  # 后复权


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StockIdentifier(BaseModel):
    """A single stock identified by market + code."""

    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$", description="市场代码")
    code: str = Field(..., min_length=6, max_length=6, description="6位股票代码")


class QuoteRequest(BaseModel):
    """Batch quote request."""

    stocks: list[StockIdentifier] = Field(
        ..., min_length=1, max_length=80, description="股票列表（最多80只）"
    )


class ChanlunRequest(BaseModel):
    """缠论分析请求。"""

    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$")
    code: str = Field(..., min_length=6, max_length=6)
    category: str = Field(default="DAY", description="K线周期")
    count: int = Field(default=800, ge=1, le=800)
    start: int = Field(default=0, ge=0)


class ComputeIndicatorsRequest(BaseModel):
    """技术指标计算请求。"""

    data: list[dict[str, Any]] = Field(..., description="OHLCV records")
    indicators: list[str] = Field(..., min_length=1, description="指标名称列表")
    params: dict[str, dict[str, int | float]] | None = Field(
        default=None, description="指标参数（可选）"
    )
    keep_ohlcv: bool = Field(default=True, description="保留原始 OHLCV 列")
    tail: int | None = Field(default=None, ge=1, description="仅返回末尾 N 行")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DataFrameResponse(BaseModel):
    """通用 DataFrame 响应（records 格式）。"""

    data: list[dict[str, Any]]
    count: int

    @classmethod
    def from_dataframe(cls, df: Any) -> DataFrameResponse:
        """从 pandas DataFrame 构建响应。"""
        import pandas as pd

        if isinstance(df, pd.DataFrame):
            records = df.to_dict(orient="records")
            cleaned: list[dict[str, Any]] = []
            for row in records:
                clean_row: dict[str, Any] = {}
                for k, v in row.items():
                    assert isinstance(k, str)
                    if hasattr(v, "isoformat"):
                        clean_row[k] = v.isoformat()
                    elif isinstance(v, float) and v != v:
                        # NaN → null：缺失值（如指数分钟线 vol，pandas 惯例 NaN），
                        # 而 Starlette JSONResponse 为 allow_nan=False，透传会 500
                        clean_row[k] = None
                    elif hasattr(v, "item"):
                        # numpy scalar → Python native
                        clean_row[k] = v.item()
                    else:
                        clean_row[k] = v
                cleaned.append(clean_row)
            return cls(data=cleaned, count=len(cleaned))
        return cls(data=[], count=0)


class DictResponse(BaseModel):
    """通用 dict 响应（用于非 DataFrame 返回值）。"""

    data: dict[str, Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DictResponse:
        """序列化 dict，将其中的 DataFrame 转为 records 格式。"""
        import pandas as pd

        cleaned: dict[str, Any] = {}
        for k, v in d.items():
            if isinstance(v, pd.DataFrame):
                cleaned[k] = DataFrameResponse.from_dataframe(v).data
            elif hasattr(v, "isoformat"):
                cleaned[k] = v.isoformat()
            elif hasattr(v, "item"):
                cleaned[k] = v.item()
            else:
                cleaned[k] = v
        return cls(data=cleaned)


class CountResponse(BaseModel):
    """简单计数响应。"""

    count: int
