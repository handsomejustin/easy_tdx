"""市场信息路由：证券列表、实时行情、市场统计、资金流向。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from easy_tdx.web.convert import market_from_str
from easy_tdx.web.deps import get_client
from easy_tdx.web.schemas import (
    CountResponse,
    DataFrameResponse,
    QuoteRequest,
)

router = APIRouter(tags=["market"])


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


@router.get("/market/core-leaders", response_model=DataFrameResponse)
async def core_leaders() -> DataFrameResponse:
    """核心龙头池（159 只，按东方财富全行业龙头名单整理）。

    数据资产供前端展示/导出；扫描场景走 ``universe="core"``（screen scan
    与 /market/strength 均支持）。
    """
    from easy_tdx.screen.universe import CORE_LEADERS

    rows = [
        {"code": code, "name": name, "market": "SH" if code.startswith(("6", "9")) else "SZ"}
        for code, name in CORE_LEADERS.items()
    ]
    return DataFrameResponse(data=rows, count=len(rows))


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
