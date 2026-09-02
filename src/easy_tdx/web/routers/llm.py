"""LLM 配置与对话路由（WebUI「AI 设置」页 + AI 解读直连）。"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from easy_tdx.ai.llm import (
    PROVIDER_PRESETS,
    LlmClient,
    LlmConfig,
    LlmError,
    config_path,
    load_config,
    mask_key,
    resolve_config,
    save_config,
)
from easy_tdx.web.backtest_schemas import TaskStateResponse, TaskSubmitResponse
from easy_tdx.web.task_runner import get_runner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["llm"])


class LlmConfigUpdate(BaseModel):
    """PUT /llm/config 请求体。

    ``api_key`` 缺省或等于当前脱敏回显值时保留原 key——前端把脱敏串原样
    回传不会把真 key 冲掉；只有填了新值才覆盖。
    """

    provider: str = Field("deepseek", description="Provider id（见 GET /llm/config providers）")
    api_url: str = Field("", description="API 地址，空 = 用该 Provider 预设")
    api_key: str = Field("", description="API Key（留空/传回脱敏串 = 不修改已存 key）")
    model: str = Field("", description="模型名，空 = 用该 Provider 默认模型")
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(
        16000, ge=64, le=128_000, description="输出上限；思考型模型的思考链计入此预算，建议 ≥16000"
    )
    timeout: float = Field(180.0, ge=5.0, le=600.0, description="读超时；报告解读建议 ≥120")
    system_prompt: str = ""


class LlmChatContext(BaseModel):
    """AI 解读附带的策略上下文（历史页「去回测」引导用，全部可缺省）。"""

    strategy: str = Field("", description="策略注册表 key（如 ma_cross）")
    strategy_label: str = Field("", description="策略中文名")
    symbol: str = Field("", description="6 位标的代码")
    category: str = Field("", description="K 线周期")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数")
    start_date: str = ""
    end_date: str = ""


class LlmChatRequest(BaseModel):
    """POST /llm/chat(/async) 请求体（如把 AI 解读 Prompt 直接发给已配置的 LLM）。"""

    prompt: str = Field(..., min_length=1, max_length=200_000)
    system_prompt: str | None = Field(None, description="None = 用配置里的默认系统提示")
    override: LlmConfigUpdate | None = Field(None, description="临时覆盖配置（不落盘，仅本次调用）")
    context: LlmChatContext | None = Field(None, description="策略上下文（随成功解读一并落历史库）")


def _merge_api_key(submitted: str, current: str) -> str:
    """按表单语义合并 api_key：留空/回传脱敏串 = 沿用；CLEAR = 清除；其余 = 覆盖。

    前端把脱敏串原样回传不会把真 key 冲掉；显式填 ``CLEAR`` 可移除已存
    key（否则换 Provider 时旧 key 会残留且 UI 无清除入口）。
    """
    key = submitted.strip()
    if not key or key == mask_key(current):
        return current
    if key.upper() == "CLEAR":
        return ""
    return key


def _override_config(override: LlmConfigUpdate | None) -> LlmConfig | None:
    """请求体临时配置 → LlmConfig（不落盘）。api_key 走 _merge_api_key 语义。"""
    if override is None:
        return None
    current = load_config()
    key = _merge_api_key(override.api_key, current.api_key)
    return LlmConfig(
        provider=override.provider,
        api_url=override.api_url.strip(),
        api_key=key,
        model=override.model.strip(),
        temperature=override.temperature,
        max_tokens=override.max_tokens,
        timeout=override.timeout,
    )


@router.get("/llm/config")
async def get_llm_config() -> dict[str, Any]:
    """当前 LLM 配置（key 脱敏）+ Provider 预设表 + 配置文件路径。"""
    cfg = load_config()
    preset = PROVIDER_PRESETS.get(cfg.provider, PROVIDER_PRESETS["custom"])
    try:
        resolved = resolve_config(cfg)
        missing: list[str] = []
        if preset.needs_key and not cfg.api_key:
            missing.append("api_key")
    except ValueError as exc:
        resolved = cfg  # type: ignore[assignment]
        missing = [str(exc)]
    return {
        "config": cfg.to_dict(mask_api_key=True),
        "providers": [p.to_dict() for p in PROVIDER_PRESETS.values()],
        "configured": not missing,
        "missing": missing,
        "config_path": str(config_path()),
        "resolved": {"api_url": resolved.api_url, "model": resolved.model},
    }


@router.put("/llm/config")
async def update_llm_config(req: LlmConfigUpdate) -> dict[str, Any]:
    """保存 LLM 配置到 llm.json（WebUI 与手工编辑同一份文件，双向兼容）。"""
    if req.provider not in PROVIDER_PRESETS:
        valid = ", ".join(PROVIDER_PRESETS)
        raise ValueError(f"未知 provider '{req.provider}'，可选: {valid}")

    current = load_config()
    new_key = _merge_api_key(req.api_key, current.api_key)

    cfg = LlmConfig(
        provider=req.provider,
        api_url=req.api_url.strip(),
        api_key=new_key,
        model=req.model.strip(),
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        timeout=req.timeout,
        system_prompt=req.system_prompt or current.system_prompt,
    )
    path = save_config(cfg)
    logger.info("LLM 配置已保存: provider=%s model=%s (%s)", cfg.provider, cfg.model, path)
    return {"ok": True, "config_path": str(path), "config": cfg.to_dict(mask_api_key=True)}


def _record_history(
    provider: str,
    model: str,
    prompt: str,
    reply: str,
    elapsed: float,
    ctx: LlmChatContext | None,
) -> None:
    """成功解读旁路落库（llm_history.db）。失败只记日志，不影响解读结果。"""
    from easy_tdx.web.llm_history_store import LlmHistoryRecord, get_llm_history_store

    try:
        get_llm_history_store().add(
            LlmHistoryRecord(
                provider=provider,
                model=model,
                prompt=prompt,
                reply=reply,
                elapsed=elapsed,
                **(ctx.model_dump() if ctx else {}),
            )
        )
    except Exception:  # noqa: BLE001 — 历史属旁路语义
        logger.exception("AI 解读历史落库失败（不影响解读结果）")


@router.post("/llm/test")
async def test_llm(override: LlmConfigUpdate | None = None) -> dict[str, Any]:
    """连通性测试：用已保存配置（或请求体内临时配置）发一句极短 ping。"""
    return await LlmClient(_override_config(override)).test()


@router.post("/llm/chat")
async def llm_chat(req: LlmChatRequest) -> dict[str, Any]:
    """一轮 LLM 对话：把 prompt（如回测报告解读 Prompt）发给已配置的模型。"""
    client = LlmClient(_override_config(req.override))
    try:
        t0 = time.perf_counter()
        reply = await client.chat(req.prompt, system_prompt=req.system_prompt)
    except LlmError as exc:
        # 全局 ValueError 处理器 → 400 {error, detail}，前端 formatError 可读展示
        raise ValueError(str(exc)) from exc
    elapsed = round(time.perf_counter() - t0, 1)
    _record_history(
        client.config.provider, client.config.model, req.prompt, reply, elapsed, req.context
    )
    return {"reply": reply, "model": client.config.model, "provider": client.config.provider}


@router.post("/llm/chat/async", response_model=TaskSubmitResponse, status_code=202)
async def llm_chat_async(req: LlmChatRequest) -> TaskSubmitResponse:
    """提交 AI 解读后台任务（长耗时模型调用不占住 HTTP 连接）。

    大报告解读 1-3 分钟，同步 HTTP 等待对代理/浏览器都不友好；这里接入
    与回测同一套任务执行器（``task_runner``，4 线程池 + SQLite 持久化），
    前端短轮询 ``GET /llm/chat/tasks/{task_id}`` 取状态，断线重连后仍可
    查询。配置不完整（缺 url/model）在提交时即报 400；网络/鉴权/超时
    类错误发生在任务内，体现在 TaskState.error。
    """
    client = LlmClient(_override_config(req.override))  # 提交期即校验配置
    desc = f"AI 解读 | {client.config.provider} · {client.config.model} | {len(req.prompt)} 字"

    def _run() -> dict[str, Any]:
        t0 = time.perf_counter()
        reply = asyncio.run(client.chat(req.prompt, system_prompt=req.system_prompt))
        elapsed = round(time.perf_counter() - t0, 1)
        _record_history(
            client.config.provider, client.config.model, req.prompt, reply, elapsed, req.context
        )
        return {
            "reply": reply,
            "model": client.config.model,
            "provider": client.config.provider,
            "elapsed": elapsed,
        }

    runner = get_runner()
    task_id = runner.submit(_run, description=desc)
    state = runner.get(task_id)
    status: Any = state.status if state.status in ("pending", "running") else "running"
    return TaskSubmitResponse(task_id=task_id, status=status)


@router.get("/llm/chat/tasks/{task_id}", response_model=TaskStateResponse)
async def llm_chat_task(task_id: str) -> TaskStateResponse:
    """查询 AI 解读任务状态（与回测任务同一存储，语义化路径别名）。"""
    runner = get_runner()
    try:
        state = runner.get(task_id)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    return TaskStateResponse(
        task_id=state.task_id,
        status=state.status,
        result=state.result,
        error=state.error,
        description=state.description,
        elapsed=(state.finished_at or time.time()) - (state.started_at or state.created_at),
    )


@router.get("/llm/history")
async def list_llm_history(limit: int = 50) -> dict[str, Any]:
    """AI 解读历史（时间倒序）。每条含 Prompt、解读正文与策略上下文。"""
    from easy_tdx.web.llm_history_store import get_llm_history_store

    items = get_llm_history_store().list_all(limit=min(max(limit, 1), 200))
    return {"items": [r.to_dict() for r in items], "count": len(items)}


@router.delete("/llm/history/{record_id}")
async def delete_llm_history(record_id: int) -> dict[str, Any]:
    """删除一条历史记录。"""
    from easy_tdx.web.llm_history_store import get_llm_history_store

    if not get_llm_history_store().delete(record_id):
        raise ValueError(f"历史记录 {record_id} 不存在")
    return {"ok": True}


@router.delete("/llm/history")
async def clear_llm_history() -> dict[str, Any]:
    """清空全部历史记录。"""
    from easy_tdx.web.llm_history_store import get_llm_history_store

    deleted = get_llm_history_store().clear()
    return {"ok": True, "deleted": deleted}
