"""市场信息路由：证券列表、实时行情、市场统计、资金流向、涨停生态。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import market_from_str
from easy_tdx.web.deps import get_client
from easy_tdx.web.schemas import (
    CountResponse,
    DataFrameResponse,
    DictResponse,
    QuoteRequest,
)

router = APIRouter(tags=["market"])

# 涨停生态结果缓存（vipdoc 盘中随通达信客户端落盘更新，60s 足够新鲜）
_limitup_cache: tuple[float, dict[str, Any]] | None = None
_LIMITUP_TTL = 60.0
# 涨停逐日历史缓存（历史数据不变，10 分钟；按 days 分键）
_limitup_history_cache: dict[int, tuple[float, dict[str, Any]]] = {}


def _df_response(df: Any) -> DataFrameResponse:
    """将 DataFrame 转为 API 响应。"""
    return DataFrameResponse.from_dataframe(df)


@router.get("/security/count", response_model=CountResponse)
async def security_count(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    client: Any = Depends(get_client),
) -> CountResponse:
    """获取市场证券总数。"""
    count = await client.get_security_count(market_from_str(market))
    return CountResponse(count=count)


@router.get("/security/list", response_model=DataFrameResponse)
async def security_list(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    start: int = Query(0, ge=0, description="分页起始位置"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取证券列表（每页约1000条）。"""
    df = await client.get_security_list(market_from_str(market), start)
    return _df_response(df)


@router.get("/security/list-all", response_model=DataFrameResponse)
async def security_list_all(
    pages: int = Query(1, ge=1, description="拉取页数（每个市场每页1000条）"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取沪深 A 股完整列表。"""
    df = await client.get_security_list_all(pages=pages)
    return _df_response(df)


@router.post("/quotes", response_model=DataFrameResponse)
async def security_quotes(
    req: QuoteRequest,
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """批量获取实时五档行情（最多80只/次）。"""
    stocks_parsed: list[tuple[Any, str]] = []
    for s in req.stocks:
        m = market_from_str(s.market)
        stocks_parsed.append((m, s.code))
    df = await client.get_security_quotes(stocks_parsed)
    return _df_response(df)


@router.get("/market/stat", response_model=DataFrameResponse)
async def market_stat(
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取 A 股全市场涨跌统计。"""
    df = await client.get_market_stat()
    return _df_response(df)


@router.get("/market/session")
async def market_session() -> dict[str, Any]:
    """A 股有效行情时段判断（供前端自动刷新门控校准）。

    窗口 09:15~11:30、13:00~15:05（含集合竞价缓冲，午休除外），周一至周五。
    节假日不做日历判断——盘外误判为盘中只会多拉一次快照，无副作用。
    """
    from easy_tdx.realtime.session import session_info

    return session_info()


@router.get("/limitup-ecology", response_model=DictResponse)
async def limitup_ecology(
    vipdoc: str | None = Query(None, description="离线数据目录（默认自动检测）"),
) -> DictResponse:
    """涨停生态：连板天梯 / 首板二板分布 / 炸板 / 跌停（本地 vipdoc 日线离线回算）。

    结果的 ``data_date`` 为 vipdoc 数据日期——数据新鲜度取决于本机通达信客户端
    的盘后下载/盘中落盘，前端必须明示该日期。全市场扫描约需数秒，结果缓存 60s。
    涨停判定按代码段：主板 10%（含 5% 疑似 ST 标记）、创业板/科创板 20%；
    .day 文件无名称，name 由前端经批量报价补齐。
    """
    global _limitup_cache
    now = time.monotonic()
    if _limitup_cache is not None and now - _limitup_cache[0] < _LIMITUP_TTL:
        return DictResponse.from_dict(_limitup_cache[1])

    def _scan() -> dict[str, Any]:
        from easy_tdx.screen.limitup import compute_limitup_ecology

        eco = compute_limitup_ecology(vipdoc)
        return {
            "data_date": eco.data_date,
            "total": eco.total,
            "summary": eco.summary(),
            "limit_up": [asdict(e) for e in eco.limit_up],
            "limit_down": [asdict(e) for e in eco.limit_down],
            "blown": [asdict(e) for e in eco.blown],
        }

    payload = await asyncio.to_thread(_scan)
    _limitup_cache = (now, payload)
    return DictResponse.from_dict(payload)


@router.get("/market/sentiment/today", response_model=DictResponse)
async def sentiment_today(
    date: int | None = Query(None, description="交易日 YYYYMMDD，缺省=最近有采样的日期"),
) -> DictResponse:
    """当日情绪分钟曲线（上涨/下跌/涨停/跌停家数、上涨占比、总成交额）。

    数据来自 :class:`easy_tdx.web.sentiment_sampler.SentimentSampler` 的盘中
    逐分钟采样——服务重启不丢（SQLite 持久化），但首次上线前无历史。
    """
    from easy_tdx.web.sentiment_store import get_sentiment_store

    store = get_sentiment_store()
    d = date or store.latest_date()
    if not d:
        return DictResponse.from_dict({"date": 0, "count": 0, "samples": []})
    rows = store.day_samples(d)
    for r in rows:
        denom = max(r["up_count"] + r["down_count"], 1)
        r["up_ratio"] = round(100.0 * r["up_count"] / denom, 1)
    return DictResponse.from_dict({"date": d, "count": len(rows), "samples": rows})


@router.get("/market/sentiment/history", response_model=DictResponse)
async def sentiment_history(
    days: int = Query(60, ge=5, le=250, description="聚合天数"),
) -> DictResponse:
    """逐日情绪聚合（收盘快照的上涨占比/涨跌停家数/成交额 + 涨停峰值）。

    同样依赖采样器的积累；涨停/跌停家数的"无采样历史"可用
    ``/market/limitup-history``（vipdoc 离线回补）替代。
    """
    from easy_tdx.web.sentiment_store import get_sentiment_store

    rows = get_sentiment_store().daily_history(days)
    return DictResponse.from_dict({"count": len(rows), "days": rows})


@router.get("/market/limitup-history", response_model=DictResponse)
async def limitup_history(
    days: int = Query(60, ge=5, le=250, description="回补交易日数"),
    vipdoc: str | None = Query(None, description="离线数据目录（默认自动检测）"),
) -> DictResponse:
    """涨停/跌停家数逐日历史（本地 vipdoc 离线回补，无需采样积累）。

    全市场扫描约需数十秒，结果缓存 10 分钟。日期覆盖受 vipdoc 数据范围限制。
    """
    global _limitup_history_cache
    now = time.monotonic()
    cached = _limitup_history_cache.get(days)
    if cached is not None and now - cached[0] < 600:
        return DictResponse.from_dict(cached[1])

    def _scan() -> dict[str, Any]:
        from easy_tdx.screen.limitup import compute_limitup_history

        rows = compute_limitup_history(vipdoc, days=days)
        return {"count": len(rows), "days": rows}

    payload = await asyncio.to_thread(_scan)
    _limitup_history_cache[days] = (now, payload)
    return DictResponse.from_dict(payload)


@router.get("/market/board-fund/history", response_model=DictResponse)
async def board_fund_history(
    days: int = Query(15, ge=1, le=90, description="返回交易日数"),
) -> DictResponse:
    """行业主力净流入逐日排行（FundFlowSampler 每交易日 14:45 后采样一条）。

    口径：涨幅前 50 名行业中主力净流入最高的 10 个（逐板块 summary 太贵，
    非全市场严格排序）。数据需采样积累，页面空态有明示。
    """
    from easy_tdx.web.sentiment_store import get_sentiment_store

    days_rows = get_sentiment_store().list_fund_days(days)
    return DictResponse.from_dict({"count": len(days_rows), "days": days_rows})


@router.get("/fund-flow", response_model=DataFrameResponse)
async def fund_flow(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取个股当日资金流向。

    口径注意：按聚合后单笔成交额分档，与东财/同花顺"主力净流入"不可比（Issue #55）。
    """
    df = await client.get_fund_flow(market_from_str(market), code)
    return _df_response(df)


@router.get("/fund-flow/history", response_model=DataFrameResponse)
async def history_fund_flow(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6, description="6位股票代码"),
    start: int = Query(0, ge=0),
    count: int = Query(100, ge=1, le=800),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取个股历史日线资金流向。

    口径注意：按聚合后单笔成交额分档，与东财/同花顺"主力净流入"不可比（Issue #55）。
    """
    df = await client.get_history_fund_flow(market_from_str(market), code, start, count)
    return _df_response(df)


@router.get("/market/strength", response_model=DataFrameResponse)
async def market_strength(
    preset: str = Query(
        "steady",
        description="预设模式: steady(中长期稳健) / breakout(近期妖股) / balanced(均衡)",
    ),
    w5: float | None = Query(None, description="自定义 5 日权重（覆盖预设）"),
    w20: float | None = Query(None, description="自定义 20 日权重（覆盖预设）"),
    w60: float | None = Query(None, description="自定义 60 日权重（覆盖预设）"),
    vol_adjusted: bool | None = Query(None, description="波动率惩罚开关（覆盖预设）"),
    top_n: int = Query(50, ge=1, le=5000, description="返回前 N 名"),
    universe: str = Query("all", description="范围: all/sh/sz/core（core=核心龙头池159只）"),
    min_listed_days: int = Query(65, ge=30, description="最小上市天数"),
    min_amount: float = Query(0.0, ge=0, description="最近 5 日日均成交额下限（元）"),
    vipdoc: str | None = Query(None, description="离线数据目录（默认自动检测）"),
) -> DataFrameResponse:
    """全市场强势股排名（基于本地通达信 .day 日线文件）。

    按 5/20/60 日涨幅加权合成强势分。三种预设：

    - **steady**: 中长期稳健（60日主导 + 波动率惩罚），选出稳着涨的票
    - **breakout**: 近期妖股爆发（5日主导，纯涨幅），选出短期最猛的票
    - **balanced**: 三周期均衡 + 波动率调整

    注意：需要本地 vipdoc 数据，扫描 ~5000 只约 30-60 秒。
    """
    import asyncio

    from easy_tdx.screen.strength import StrengthRanker

    ranker = StrengthRanker(
        vipdoc_path=vipdoc,
        preset=preset,
        w5=w5,
        w20=w20,
        w60=w60,
        vol_adjusted=vol_adjusted,
        min_listed_days=min_listed_days,
        min_amount=min_amount,
    )

    # Web 端用线程池执行，避免阻塞事件循环（扫描全市场耗时较长）
    # 注：在协程内用 get_running_loop() 而非 get_event_loop()，
    # 后者在 Python 3.12+ 已弃用。
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, lambda: ranker.rank(universe=universe, top_n=top_n))

    records = [
        {
            "rank": r.rank,
            "code": r.code,
            "market": r.market,
            "name": r.name,
            "last_close": r.last_close,
            "last_date": r.last_date,
            "ret_5": r.ret_5,
            "ret_20": r.ret_20,
            "ret_60": r.ret_60,
            "vol_20": r.vol_20,
            "strength": r.strength,
        }
        for r in results
    ]
    return DataFrameResponse(data=records, count=len(records))
