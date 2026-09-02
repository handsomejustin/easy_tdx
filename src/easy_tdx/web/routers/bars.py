"""K线 / 分时 / 逐笔成交路由。"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query

from easy_tdx._df import _category_to_minutes
from easy_tdx.web.convert import (
    adjust_from_str,
    category_from_str,
    market_from_str,
    market_value_from_str,
    period_times_from_category,
)
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.schemas import DataFrameResponse

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["bars"])

# 规整后保持的列顺序（匹配旧 SecurityBar 输出契约）
_NORMAL_COLS = ["open", "close", "high", "low", "vol", "amount"]


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


def _is_daily_plus(cat: Any) -> bool:
    """判断 KlineCategory 是否日线及以上周期（datetime 应归一为 date）。

    KlineCategory 的枚举值不按周期长短排序（MIN_1=7、MIN_3=8 均大于 DAY=4），
    不能用整数大小判断"日线及以上"；与 client.py 的 get_security_bars 路径保持
    同一判定源：_CATEGORY_MINUTES 查得到=分钟级，查不到=日线及以上。
    """
    return _category_to_minutes(int(cat)) is None


def _normalize_mac_df(df: pd.DataFrame, daily_plus: bool) -> pd.DataFrame:
    """规整 MacClient.get_stock_kline 的输出以匹配旧 /bars 契约。

    MacClient 返回 ``datetime`` 列（含时分秒）+ ``float_shares`` 列，OHLC 顺序为
    open/high/low/close。旧 /bars（SecurityBar 路径）日线返回 ``date`` 列（仅日期）、
    分钟线返回 ``datetime`` 列，无 float_shares，OHLC 顺序为 open/close/high/low。
    本函数做对齐，保证迁移后调用方输出契约不变。

    Args:
        df: MacClient 返回的 DataFrame（可能为空）。
        daily_plus: True=日线及以上周期（datetime→date），False=分钟线（保留 datetime）。
    """
    if df.empty:
        return df
    out = df.copy()
    if "float_shares" in out.columns:
        out = out.drop(columns=["float_shares"])
    time_col = "date" if daily_plus else "datetime"
    if "datetime" in out.columns:
        if daily_plus:
            # 截断为仅日期（00:00:00），与旧 _merge_bar_datetime 的 date 列语义一致
            out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
        out = out.rename(columns={"datetime": time_col})
    # 重排列顺序：时间列在前，OHLC 顺序 open/close/high/low，再 vol/amount
    cols = [c for c in [time_col, *_NORMAL_COLS] if c in out.columns]
    # 兜底：保留未列出的列（理论上不应有），追加到末尾
    cols += [c for c in out.columns if c not in cols]
    return out[cols]


@router.get("/bars", response_model=DataFrameResponse)
async def security_bars(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    code: str = Query(..., min_length=6, max_length=6),
    category: str = Query(
        "DAY",
        description="K线周期: MIN_1, MIN_5, MIN_15, MIN_30, MIN_60, DAY, WEEK, MONTH, YEAR",
    ),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    bar_time: str = Query(
        "start", description="时间戳: start=bar开始时间(默认) / end=bar结束时间(对齐Tushare)"
    ),
    adjust: str = Query(
        "QFQ", description="复权: NONE=不复权 / QFQ=前复权(默认) / HFQ=后复权（需 MAC 客户端）"
    ),
    mac_client: Any = Depends(get_mac_client_optional),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取股票K线数据（MAC 协议，支持复权）。

    优先走 AsyncMacClient.get_stock_kline（支持 NONE/QFQ/HFQ 复权 + QFQ 负价兜底）；
    MAC 主机未连接时自动回退 AsyncTdxClient.get_security_bars（无复权，adjust 参数忽略）。
    输出契约与旧版一致：日线返回 ``date`` 列，分钟线返回 ``datetime`` 列。

    vol 单位：分钟线/日线 = 成交量(股)；周/月/季/年线服务端原样返回真实
    成交量/100，回退路径（标准 TdxClient）已 ×100 还原为股。
    """
    cat = category_from_str(category)
    if mac_client is not None:
        period, times = period_times_from_category(cat)
        df = await mac_client.get_stock_kline(
            market_value_from_str(market),
            code,
            period,
            start,
            count,
            times,
            adjust=adjust_from_str(adjust),
            bar_time=bar_time,
        )
        # daily_plus：日线及以上周期 datetime→date（枚举值无序，显式查表判定）
        df = _normalize_mac_df(df, daily_plus=_is_daily_plus(cat))
    else:
        # MAC 不可用：回退标准 TdxClient（无复权），adjust 参数忽略
        _logger.warning(
            "/bars MAC 客户端未连接，回退标准 TdxClient（不支持复权，adjust=%s 被忽略）",
            adjust,
        )
        df = await client.get_security_bars(
            market_from_str(market), code, cat, start, count, bar_time=bar_time
        )
    return _df_resp(df)


@router.get("/bars/index", response_model=DataFrameResponse)
async def index_bars(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    category: str = Query("DAY", description="K线周期"),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    bar_time: str = Query(
        "start", description="时间戳: start=bar开始时间(默认) / end=bar结束时间(对齐Tushare)"
    ),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取指数K线数据。

    vol 单位：日线/周线/月线/季线/年线 = 成交量(手)（周及以上周期服务端
    原样返回真实成交量/100，已 ×100 还原）；**分钟线协议不提供成交量**
    （报文中该字段实为成交额/100），vol 为 ``null``，请勿当作成交量使用。
    """
    df = await client.get_index_bars(
        market_from_str(market), code, category_from_str(category), start, count, bar_time=bar_time
    )
    return _df_resp(df)


@router.get("/minute", response_model=DataFrameResponse)
async def minute_time(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取今日分时数据。"""
    df = await client.get_minute_time_data(market_from_str(market), code)
    return _df_resp(df)


@router.get("/minute/history", response_model=DataFrameResponse)
async def history_minute_time(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    date: int = Query(..., description="日期 YYYYMMDD"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取历史某日分时数据。"""
    df = await client.get_history_minute_time_data(market_from_str(market), code, date)
    return _df_resp(df)


@router.get("/transaction", response_model=DataFrameResponse)
async def transaction_data(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取当日逐笔成交。"""
    df = await client.get_transaction_data(market_from_str(market), code, start, count)
    return _df_resp(df)


@router.get("/transaction/history", response_model=DataFrameResponse)
async def history_transaction_data(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    date: int = Query(..., description="日期 YYYYMMDD"),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取历史逐笔成交。"""
    df = await client.get_history_transaction_data(
        market_from_str(market), code, date, start, count
    )
    return _df_resp(df)
