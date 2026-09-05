"""板块分析路由：板块列表、成分、归属、摘要、涨幅排名、N日涨幅、热点滚动。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query

from easy_tdx.mac.enums import Adjust, Period
from easy_tdx.web.convert import (
    board_sort_from_str,
    board_type_from_str,
    market_value_from_str,
    sort_order_from_str,
    sort_type_from_str,
)
from easy_tdx.web.deps import get_mac_client
from easy_tdx.web.schemas import DataFrameResponse, DictResponse

_logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# 热点滚动（/board-mac/hotspot）：交易日 × 板块 每日涨跌矩阵 + 每日排名
#
# 两段式数据合成：
# - 历史矩阵：逐板块拉板块指数日K（get_stock_kline），close 逐日环比得涨跌幅，
#   收盘后不可变 → 按日历日缓存全天有效；days 参数只做切片，不进缓存键。
# - 今日列：实时报价 price/pre_close-1（与 overview 同口径）；全市场无一移动
#   （盘前/休市/节假日）则不追加今日列，避免出现全 0 的假列。
#
# AsyncMacClient 是单连接串行，概念板块（~500 个）首次构建需数十秒：
# 构建放 asyncio 后台任务 + 进度轮询，避免占住请求线程并拖死同连接的其他页面。
# ---------------------------------------------------------------------------

# 历史矩阵最大窗口（days 参数在其内切片）与多拉的缓冲 bar（窗口首日前收 + 节假日）
_HOTSPOT_MAX_DAYS = 60
_HOTSPOT_FETCH_BUFFER = 12
_HOTSPOT_KLINE_COUNT = _HOTSPOT_MAX_DAYS + _HOTSPOT_FETCH_BUFFER
_HOTSPOT_MAX_ROWS = 60  # 返回行数上限（行集合按上榜次数截断）
_HOTSPOT_KLINE_CONCURRENCY = 8  # 单连接实际串行，信号量只做秩序与背压

# board_type 名 -> (日历日, {axis: 日期轴, pct: {code: {日期: 涨跌幅}}, names: {code: 名称}})
_hotspot_history_cache: dict[str, tuple[str, dict[str, Any]]] = {}
# board_type 名 -> 构建状态 {"status": "building"|"ready"|"error", "progress", "task", "error"}
_hotspot_builds: dict[str, dict[str, Any]] = {}


def _today_str() -> str:
    """当日日历日（缓存失效键；单测可 monkeypatch）。"""
    return datetime.now().strftime("%Y-%m-%d")


async def _hotspot_build(board_key: str, bt: Any, client: Any) -> None:
    """后台构建板块历史日度涨跌矩阵，结果写入 _hotspot_history_cache。"""
    state = _hotspot_builds[board_key]
    try:
        boards_df = await client.get_board_list(board_type=bt, count=5000)
        if boards_df is None or boards_df.empty:
            raise ValueError("板块列表为空，无法构建热点矩阵")
        entries = [
            (str(rec["code"]), int(rec.get("market") or 1))
            for rec in boards_df.to_dict(orient="records")
        ]
        names = {
            str(rec["code"]): str(rec.get("name") or rec["code"])
            for rec in boards_df.to_dict(orient="records")
        }
        total = len(entries)
        sem = asyncio.Semaphore(_HOTSPOT_KLINE_CONCURRENCY)
        done = 0

        async def fetch_one(code: str, market: int) -> tuple[str, pd.DataFrame | None]:
            nonlocal done
            async with sem:
                try:
                    df = await client.get_stock_kline(
                        market=market,
                        code=code,
                        period=Period.DAILY,
                        count=_HOTSPOT_KLINE_COUNT,
                        adjust=Adjust.NONE,
                    )
                except Exception:  # noqa: BLE001 — 单板块缺K线不阻塞整体
                    df = None
            done += 1
            state["progress"] = round(done / total, 4)
            return code, df

        fetched = await asyncio.gather(*(fetch_one(code, market) for code, market in entries))

        pct_map: dict[str, dict[str, float]] = {}
        for code, df in fetched:
            if df is None or df.empty or len(df) < 2 or "datetime" not in df.columns:
                continue
            kline = df.sort_values("datetime")
            dates = pd.to_datetime(kline["datetime"]).dt.strftime("%Y-%m-%d").reset_index(drop=True)
            close = pd.to_numeric(kline["close"], errors="coerce").reset_index(drop=True)
            pct = (close / close.shift(1) - 1.0) * 100.0
            series: dict[str, float] = {}
            for d, p in zip(dates.iloc[1:], pct.iloc[1:]):  # 首根无前收，跳过
                if pd.notna(p):
                    series[str(d)] = round(float(p), 3)
            if series:
                pct_map[code] = series
        if not pct_map:
            raise ValueError("全部板块日K获取失败，无法构建热点矩阵")

        # 交易日轴 = 数据最全板块的日期序列（全市场板块共享交易日历）
        axis = sorted(max(pct_map.values(), key=len).keys())
        _hotspot_history_cache[board_key] = (
            _today_str(),
            {"axis": axis, "pct": pct_map, "names": names},
        )
        state["status"] = "ready"
        state["progress"] = 1.0
    except Exception as exc:  # noqa: BLE001 — 构建失败转可轮询的 error 状态，不抛出
        state["status"] = "error"
        state["error"] = str(exc)
        _logger.warning("热点矩阵构建失败 (%s): %s", board_key, exc)


def _hotspot_history_or_build(
    key: str,
    bt: Any,
    client: Any,
    *,
    retry: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """热点历史缓存的公共入口。

    缓存就绪返回 ``(history, None)``；否则触发/汇报后台构建，返回
    ``(None, building_or_error_payload)``。error 状态保持稳定不自动重建，
    保证失败原因能被前端读到（``retry=1`` 才重建）。
    """
    cached = _hotspot_history_cache.get(key)
    if cached is not None and cached[0] == _today_str():
        return cached[1], None
    state = _hotspot_builds.get(key)
    running = state is not None and state.get("task") is not None and not state["task"].done()
    # 需要新建：无状态 / 上次成功但缓存已过期 / 显式重试
    if not running and (retry or state is None or state.get("status") == "ready"):
        state = {"status": "building", "progress": 0.0, "task": None, "error": ""}
        _hotspot_builds[key] = state
        state["task"] = asyncio.create_task(_hotspot_build(key, bt, client))
        running = True
    if running:
        return None, {"status": "building", "progress": state.get("progress", 0.0)}
    return None, {
        "status": "error",
        "error": state.get("error") or "热点矩阵构建失败",
        "progress": 1.0,
    }


@router.get("/board-mac/hotspot", response_model=DictResponse)
async def board_hotspot(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    days: int = Query(20, ge=1, le=_HOTSPOT_MAX_DAYS, description="窗口交易日数（1=仅今日）"),
    mode: str = Query("top", description="top=领涨(每日最强入选) / bottom=领跌(每日最弱入选)"),
    per_day: int = Query(5, ge=2, le=10, description="每日入选名次阈值"),
    retry: bool = Query(False, description="上次构建失败后强制重建"),
    client: Any = Depends(get_mac_client),
) -> DictResponse:
    """市场热点滚动：交易日 × 板块 每日涨跌矩阵 + 当日排名。

    首次请求某板块类型时启动后台构建，返回 ``{"status": "building", "progress": 0~1}``，
    前端 ~1s 轮询直至 ``ready``。构建失败返回 ``{"status": "error", "error": ...}``
    并保持稳定（轮询不会自动重建，避免错误被冲掉）；带 ``retry=1`` 再次请求即重建。
    ``session`` 为 ``live`` 表示最后一列是盘中实时值。

    行集合 = 窗口内「每日 mode 方向前 per_day 名」板块的并集（按上榜次数截断至
    ``_HOTSPOT_MAX_ROWS`` 行）。``rank`` 为当日全类型排名：mode=top 时 1=涨幅最大，
    mode=bottom 时 1=跌幅最大。``sum_pct`` 为窗口内逐日复利累计。
    """
    mode_norm = mode.strip().lower()
    if mode_norm not in ("top", "bottom"):
        raise ValueError(f"mode 仅支持 top/bottom，got {mode}")

    bt = board_type_from_str(board_type)
    key = bt.name

    history, build_payload = _hotspot_history_or_build(key, bt, client, retry=retry)
    if build_payload is not None:
        return DictResponse.from_dict(build_payload)
    axis_all: list[str] = history["axis"]
    pct_map: dict[str, dict[str, float]] = history["pct"]
    names: dict[str, str] = dict(history["names"])

    # 窗口切片：剔除今日（今日列一律来自实时报价，避免日K盘中未完成 bar 混入）
    today = _today_str()
    window = [d for d in axis_all if d != today][-days:]

    # 今日列：实时报价（1–2 页，廉价）。全市场无一移动（盘前/休市）则不追加
    live_df = await client.get_board_list(board_type=bt, count=5000)
    live_change: dict[str, float] = {}
    any_moved = False
    if live_df is not None and not live_df.empty:
        for rec in live_df.to_dict(orient="records"):
            code = str(rec["code"])
            if rec.get("name"):
                names[code] = str(rec["name"])
            price = float(rec.get("price") or 0.0)
            pre = float(rec.get("pre_close") or 0.0)
            if price > 0 and pre > 0:
                chg = round((price / pre - 1.0) * 100.0, 3)
                live_change[code] = chg
                if abs(chg) > 1e-9:
                    any_moved = True
    col_pct: list[dict[str, float]] = [
        {code: m[d] for code, m in pct_map.items() if d in m} for d in window
    ]
    # 周末/节假日隔夜：TDX 的 pre_close 尚未滚动，实时涨跌会与历史末列几乎完全
    # 重合（都是上一交易日的涨幅）——重合度过高则不追加，避免出现重复的假今日列。
    # 交易日盘中实时值与昨日收盘涨幅必然大面积偏离，不受此判定影响。
    if any_moved and window:
        last_col = col_pct[-1]
        same = diff = 0
        for code, chg in live_change.items():
            prev = last_col.get(code)
            if prev is None:
                continue
            if abs(chg - prev) <= 0.05:
                same += 1
            else:
                diff += 1
        append_live = (same + diff) > 0 and diff / (same + diff) >= 0.5
    else:
        append_live = False
    if append_live:
        col_pct.append(live_change)

    dates = window + ([today] if append_live else [])

    # 每列全类型排名（mode 方向；1 = 最强/最弱）
    col_rank: list[dict[str, int]] = []
    for col in col_pct:
        ordered = sorted(col.items(), key=lambda kv: kv[1], reverse=(mode_norm == "top"))
        col_rank.append({code: i + 1 for i, (code, _) in enumerate(ordered)})

    # 行集合 = 每日前 per_day 名的并集；行内元数据在完整窗口（含今日列）上统计
    in_top: list[set[str]] = [{c for c, r in rank.items() if r <= per_day} for rank in col_rank]
    candidates: set[str] = set().union(*in_top) if in_top else set()

    rows_out: list[dict[str, Any]] = []
    for code in candidates:
        pct_arr = [col.get(code) for col in col_pct]
        rank_arr = [rank.get(code) for rank in col_rank]
        top_flags = [r is not None and r <= per_day for r in rank_arr]
        best: int | None = None
        comp = 1.0
        has_data = False
        for p, r in zip(pct_arr, rank_arr):
            if p is not None:
                has_data = True
                comp *= 1.0 + p / 100.0
            if r is not None and (best is None or r < best):
                best = r
        first_date = next((dates[i] for i, f in enumerate(top_flags) if f), None)
        rows_out.append(
            {
                "code": code,
                "name": names.get(code, code),
                "pct": pct_arr,
                "rank": rank_arr,
                "days_in": sum(top_flags),
                "streak": _trailing_streak(top_flags),
                "best_rank": best,
                "sum_pct": round((comp - 1.0) * 100.0, 2) if has_data else None,
                "first_date": first_date,
            }
        )
    rows_out.sort(
        key=lambda r: (
            -r["days_in"],
            -(r["sum_pct"] or 0.0),
            r["best_rank"] if r["best_rank"] else 9999,
            r["code"],  # 全并列时按代码兜底：candidates 来自 set，迭代序跨进程不稳定
        )
    )
    rows_out = rows_out[:_HOTSPOT_MAX_ROWS]

    from easy_tdx.realtime.session import is_trading_time

    payload: dict[str, Any] = {
        "status": "ready",
        "board_type": bt.name,
        "days": days,
        "mode": mode_norm,
        "per_day": per_day,
        "generated_at": int(time.time()),
        "session": "live" if (append_live and is_trading_time()) else "closed",
        "dates": dates,
        "today_index": (len(dates) - 1) if append_live else None,
        "total_boards": len(pct_map),
        "rows": rows_out,
    }
    return DictResponse.from_dict(payload)


@router.get("/board-mac/hotspot-correlation", response_model=DictResponse)
async def board_hotspot_correlation(
    board_type: str = Query("HY", description="板块类型: HY/HY2/GN/FG/DQ"),
    days: int = Query(20, ge=5, le=_HOTSPOT_MAX_DAYS, description="相关性窗口交易日数"),
    per_day: int = Query(5, ge=2, le=10, description="每日入选名次阈值（行集合口径）"),
    top: int = Query(15, ge=5, le=25, description="入阵板块数上限（按上榜次数取前 N）"),
    client: Any = Depends(get_mac_client),
) -> DictResponse:
    """热点板块相关性矩阵：窗口内活跃板块两两日涨跌幅的 Pearson 相关系数。

    行集合与 ``/board-mac/hotspot`` 同口径（每日 mode=top 前 per_day 名的并集，
    不含今日实时列），按上榜次数取前 ``top`` 个板块入阵。复用热点历史矩阵缓存
    （无缓存时返回与 hotspot 相同的 building/error 状态，前端先拉 hotspot 即可）。
    相关系数 >0（红）= 同涨同跌，<0（绿）= 跷跷板。
    """
    bt = board_type_from_str(board_type)
    key = bt.name

    history, build_payload = _hotspot_history_or_build(key, bt, client)
    if build_payload is not None:
        return DictResponse.from_dict(build_payload)

    axis_all: list[str] = history["axis"]
    pct_map: dict[str, dict[str, float]] = history["pct"]
    names: dict[str, str] = dict(history["names"])

    # 仅用已完成交易日（不含今日），与热点矩阵的历史段对齐
    window = [d for d in axis_all if d != _today_str()][-days:]
    col_pct: list[dict[str, float]] = [
        {c: m[d] for c, m in pct_map.items() if d in m} for d in window
    ]
    in_top: list[set[str]] = [
        set(sorted(col, key=lambda c: col[c], reverse=True)[:per_day]) for col in col_pct
    ]
    days_in: dict[str, int] = {}
    for s in in_top:
        for c in s:
            days_in[c] = days_in.get(c, 0) + 1

    # 排序必须确定性：days_in 并列时按代码兜底——set 迭代序受哈希随机化影响，
    # 跨进程不稳定，会导致相关矩阵行列顺序在服务重启后随机互换
    chosen = sorted(days_in, key=lambda c: (-days_in[c], c))[:top]
    if len(chosen) < 2:
        return DictResponse.from_dict(
            {"status": "ready", "boards": [], "matrix": [], "days": len(window)}
        )

    frame = pd.DataFrame({c: pct_map[c] for c in chosen}).T  # 板块 × 交易日，缺失为 NaN
    corr = frame.T.corr(min_periods=max(3, len(window) // 2))

    boards = [
        {"code": c, "name": names.get(c, c), "days_in": days_in[c]} for c in chosen
    ]
    matrix: list[list[float | None]] = [
        [
            None if pd.isna(corr.loc[a, b]) else round(float(corr.loc[a, b]), 2)
            for b in chosen
        ]
        for a in chosen
    ]
    return DictResponse.from_dict(
        {
            "status": "ready",
            "board_type": bt.name,
            "days": days,
            "boards": boards,
            "matrix": matrix,
        }
    )


def _trailing_streak(flags: list[bool]) -> int:
    """从末尾向前数连续 True（末位为 False 时对齐"当前连榜"语义返 0）。"""
    if not flags or not flags[-1]:
        return 0
    n = 0
    for f in reversed(flags):
        if not f:
            break
        n += 1
    return n
