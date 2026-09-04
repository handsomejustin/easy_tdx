"""板块分析路由：板块列表、成分、归属、摘要、涨幅排名、N日涨幅。"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import (
    board_sort_from_str,
    board_type_from_str,
    market_value_from_str,
    sort_order_from_str,
    sort_type_from_str,
)
from easy_tdx.web.deps import get_mac_client
from easy_tdx.web.schemas import DataFrameResponse, DictResponse

router = APIRouter(tags=["board-mac"])

# overview 端点：metrics 参数名 → 返回行字段名（值来自对应排序键的 sort_value）
_OVERVIEW_METRIC_FIELDS: dict[str, str] = {
    "SPEED": "speed",
    "CHANGE_3D": "chg_3d",
    "CHANGE_5D": "chg_5d",
    "CHANGE_10D": "chg_10d",
    "CHANGE_20D": "chg_20d",
    "CHANGE_60D": "chg_60d",
    "YTD": "chg_ytd",
}
_OVERVIEW_TTL = 15.0
# (board_type, metrics) -> (monotonic 截止时间, payload)。无锁：并发重复拉取
# 无害（AsyncMacClient 连接内本就串行），省去跨事件循环的锁生命周期问题。
_overview_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any]]] = {}

# 可在单测中 monkeypatch 以控制 TTL 判定
_now = time.monotonic


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


@router.get("/board-mac/list", response_model=DataFrameResponse)
async def board_list(
    board_type: str = Query("ALL", description="板块类型: ALL/HY/HY2/GN/FG/DQ"),
    count: int = Query(500, ge=1, le=50000),
    sort_column: str = Query(
        "CHANGE_PCT",
        description=(
            "排序键: CHANGE_PCT/SPEED/CHANGE_3D/CHANGE_5D/CHANGE_10D/"
            "CHANGE_20D/CHANGE_60D/YTD；sort_value 列即该指标值"
            "（CHANGE_PCT 时恒 0，涨跌幅=price/pre_close-1）"
        ),
    ),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块列表（默认按涨跌幅降序；要取涨速传 sort_column=SPEED）。"""
    df = await client.get_board_list(
        board_type=board_type_from_str(board_type),
        count=count,
        sort_column=board_sort_from_str(sort_column),
    )
    return _df_resp(df)


@router.get("/board-mac/members", response_model=DataFrameResponse)
async def board_members(
    board_symbol: str = Query(..., description="板块代码，如 881001"),
    count: int = Query(100, ge=1, le=100000),
    sort_type: str = Query("CHANGE_PCT", description="排序字段"),
    sort_order: str = Query("DESC", description="排序方向: ASC/DESC"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块成分股。"""
    df = await client.get_board_members(
        board_symbol=board_symbol,
        count=count,
        sort_type=sort_type_from_str(sort_type),
        sort_order=sort_order_from_str(sort_order),
    )
    return _df_resp(df)


@router.get("/board-mac/belong", response_model=DataFrameResponse)
async def board_belong(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取股票所属板块列表。"""
    df = await client.get_belong_board(market=market_value_from_str(market), code=code)
    return _df_resp(df)


@router.get("/board-mac/summary", response_model=DictResponse)
async def board_summary(
    board_symbol: str = Query(..., description="板块代码，如 881001"),
    sort_type: str = Query("CHANGE_PCT", description="排序字段"),
    sort_order: str = Query("DESC", description="排序方向: ASC/DESC"),
    client: Any = Depends(get_mac_client),
) -> DictResponse:
    """获取板块摘要信息（含成分股资金流向）。"""
    result = await client.get_board_summary(
        board_symbol=board_symbol,
        sort_type=sort_type_from_str(sort_type),
        sort_order=sort_order_from_str(sort_order),
    )
    return DictResponse.from_dict(result)


@router.get("/board-mac/ranking", response_model=DataFrameResponse)
async def board_ranking(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    top_n: int = Query(10, ge=1, le=200),
    sort_by: str = Query("change_pct", description="排序字段名"),
    ascending: bool = Query(False, description="是否升序"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块涨幅排名。"""
    df = await client.get_board_ranking(
        board_type=board_type_from_str(board_type),
        top_n=top_n,
        sort_by=sort_by,
        ascending=ascending,
    )
    return _df_resp(df)


@router.get("/board-mac/change-ranking", response_model=DataFrameResponse)
async def board_change_ranking(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    days: int = Query(20, ge=1, le=250, description="统计天数"),
    top_n: int = Query(10, ge=1, le=200),
    target_date: int | None = Query(None, description="目标日期，如 20250101"),
    ascending: bool = Query(False, description="是否升序"),
    client: Any = Depends(get_mac_client),
) -> DataFrameResponse:
    """获取板块 N 日涨幅排名。"""
    df = await client.get_board_change_ranking(
        board_type=board_type_from_str(board_type),
        target_date=target_date,
        days=days,
        top_n=top_n,
        ascending=ascending,
    )
    return _df_resp(df)


@router.get("/board-mac/overview", response_model=DictResponse)
async def board_overview(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    metrics: str = Query(
        "SPEED,CHANGE_3D,CHANGE_5D,CHANGE_20D,YTD",
        description=(
            "附加指标（逗号分隔，取自各排序键的 sort_value）: "
            "SPEED/CHANGE_3D/CHANGE_5D/CHANGE_10D/CHANGE_20D/CHANGE_60D/YTD"
        ),
    ),
    count: int = Query(2000, ge=1, le=20000),
    client: Any = Depends(get_mac_client),
) -> DictResponse:
    """板块总览：一次返回全部板块的当日涨跌幅 + 领涨股 + 多周期指标。

    以默认（涨跌幅）排序的板块列表为基表归并各 metrics 排序列的 sort_value，
    避免前端直连 N 次 ``/board-mac/list``。结果服务端缓存 15s。
    当日涨跌幅按 price/pre_close-1 计算（CHANGE_PCT 的 sort_value 恒 0）。
    """
    bt = board_type_from_str(board_type)
    sort_names = [m.strip().upper() for m in metrics.split(",") if m.strip()]
    invalid = [m for m in sort_names if m not in _OVERVIEW_METRIC_FIELDS]
    if invalid:
        valid = ", ".join(_OVERVIEW_METRIC_FIELDS)
        raise ValueError(f"无效指标 '{','.join(invalid)}'，可选值: {valid}")

    cache_key = (bt.name, tuple(sort_names))
    cached = _overview_cache.get(cache_key)
    if cached is not None and _now() < cached[0]:
        return DictResponse.from_dict(cached[1])

    results = await asyncio.gather(
        client.get_board_list(board_type=bt, count=count),
        *(
            client.get_board_list(board_type=bt, count=count, sort_column=board_sort_from_str(name))
            for name in sort_names
        ),
    )
    base_df, metric_dfs = results[0], list(results[1:])

    metric_values: dict[str, dict[str, float]] = {}
    for name, df in zip(sort_names, metric_dfs):
        field = _OVERVIEW_METRIC_FIELDS[name]
        col: dict[str, float] = {}
        if df is not None and not df.empty:
            for code, value in zip(df["code"], df["sort_value"]):
                col[str(code)] = float(value)
        metric_values[field] = col

    rows: list[dict[str, Any]] = []
    if base_df is not None and not base_df.empty:
        for record in base_df.to_dict(orient="records"):
            price = float(record["price"])
            pre_close = float(record["pre_close"])
            sym_price = float(record.get("symbol_price") or 0.0)
            sym_pre_close = float(record.get("symbol_pre_close") or 0.0)
            row: dict[str, Any] = {
                "market": int(record["market"]),
                "code": str(record["code"]),
                "name": str(record["name"]),
                "price": price,
                "pre_close": pre_close,
                "change_pct": round((price / pre_close - 1) * 100, 3) if pre_close else None,
                "leader_code": str(record.get("symbol_code") or ""),
                "leader_name": str(record.get("symbol_name") or ""),
                "leader_change_pct": (
                    round((sym_price / sym_pre_close - 1) * 100, 3) if sym_pre_close else None
                ),
            }
            for field, values in metric_values.items():
                row[field] = values.get(str(record["code"]))
            # 未请求的指标字段补 null，保证行结构稳定（前端类型固定）
            for field in _OVERVIEW_METRIC_FIELDS.values():
                row.setdefault(field, None)
            rows.append(row)

    payload = {"board_type": bt.name, "ts": int(time.time()), "count": len(rows), "rows": rows}
    _overview_cache[cache_key] = (_now() + _OVERVIEW_TTL, payload)
    return DictResponse.from_dict(payload)
