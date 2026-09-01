"""自选股路由：加入 / 列出 / 移除（SQLite 持久化，无行情依赖）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from easy_tdx.web.watchlist_store import get_watchlist_store

router = APIRouter(tags=["watchlist"])


class WatchItemAdd(BaseModel):
    """加入自选请求。name 由前端从行情数据带过来。"""

    market: str = Field(..., pattern=r"^(SZ|SH|BJ)$")
    code: str = Field(..., min_length=6, max_length=6)
    name: str = Field("", max_length=64)
    group: str = Field("默认", max_length=32)


class WatchlistResponse(BaseModel):
    items: list[dict[str, object]]
    count: int


@router.get("/watchlist", response_model=WatchlistResponse)
async def list_watchlist(
    group: str | None = Query(None, description="按分组过滤"),
) -> WatchlistResponse:
    """列出全部自选（按加入顺序）。"""
    items = get_watchlist_store().list_all(group=group)
    return WatchlistResponse(items=[i.to_dict() for i in items], count=len(items))


@router.post("/watchlist", response_model=dict[str, object])
async def add_watch_item(req: WatchItemAdd) -> dict[str, object]:
    """加入自选（幂等：重复加入仅刷新名称）。"""
    item = get_watchlist_store().add(req.market, req.code, name=req.name, group=req.group)
    return {"ok": True, "item": item.to_dict()}


@router.delete("/watchlist/{market}/{code}", response_model=dict[str, object])
async def remove_watch_item(market: str, code: str) -> dict[str, object]:
    """移除自选。"""
    if market.upper() not in {"SZ", "SH", "BJ"}:
        raise HTTPException(status_code=400, detail=f"非法市场: {market}")
    removed = get_watchlist_store().remove(market, code)
    if not removed:
        raise HTTPException(status_code=404, detail=f"自选中不存在 {market}{code}")
    return {"ok": True}
