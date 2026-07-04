"""策略库路由：列出 / 查看 / 保存 / 删除用户收藏的策略。

设计要点：
- 持久化走 :class:`~easy_tdx.web.strategy_store.StrategyStore`（SQLite 单文件），
  与回测路由解耦——本路由纯数据 CRUD，不依赖行情连接。
- 纯计算路径，不注入 tdx_client（与 backtest router 同理由）。
- ``app_version`` 从 importlib.metadata 取，缺失时留空。
"""

from __future__ import annotations

from fastapi import APIRouter

from easy_tdx.web.backtest_schemas import (
    SavedStrategy,
    SavedStrategyCreate,
    SavedStrategyListResponse,
)
from easy_tdx.web.strategy_store import (
    SavedStrategy as SavedStrategyRecord,
)
from easy_tdx.web.strategy_store import (
    get_store,
)

router = APIRouter(tags=["strategies"])


def _app_version() -> str:
    try:
        from importlib.metadata import version

        return version("easy-tdx")
    except Exception:  # noqa: BLE001 — importlib 在某些环境不可用，留空即可
        return ""


def _to_response(rec: SavedStrategyRecord) -> SavedStrategy:
    """dataclass 记录 → Pydantic 响应模型。"""
    return SavedStrategy(**rec.to_dict())


@router.get("/strategies", response_model=SavedStrategyListResponse)
async def list_saved_strategies() -> SavedStrategyListResponse:
    """列出全部已保存策略（按创建时间倒序）。"""
    store = get_store()
    items = [_to_response(r) for r in store.list_all()]
    return SavedStrategyListResponse(strategies=items, count=len(items))


@router.get("/strategies/{strategy_id}", response_model=SavedStrategy)
async def get_saved_strategy(strategy_id: str) -> SavedStrategy:
    """按 id 查看单条已保存策略。"""
    store = get_store()
    rec = store.get(strategy_id)
    if rec is None:
        raise ValueError(f"策略 '{strategy_id}' 不存在")
    return _to_response(rec)


@router.post("/strategies", response_model=SavedStrategy, status_code=201)
async def create_saved_strategy(req: SavedStrategyCreate) -> SavedStrategy:
    """保存一条策略（含当时的标的上下文与成绩快照）。"""
    store = get_store()
    rec = SavedStrategyRecord(
        id="",  # store.add 会自动生成
        name=req.name,
        kind=req.kind,
        strategy=req.strategy,
        strategy_label=req.strategy_label,
        params=req.params,
        context=req.context,
        trade_config=req.trade_config,
        snapshot=req.snapshot,
        tags=req.tags,
        notes=req.notes,
        app_version=_app_version(),
    )
    saved = store.add(rec)
    return _to_response(saved)


@router.delete("/strategies/{strategy_id}", status_code=204)
async def delete_saved_strategy(strategy_id: str) -> None:
    """按 id 删除一条已保存策略。不存在则 404。"""
    store = get_store()
    if not store.delete(strategy_id):
        raise ValueError(f"策略 '{strategy_id}' 不存在")
