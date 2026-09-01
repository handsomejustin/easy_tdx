"""实时行情 SSE 路由。

``GET /api/v1/stream/quotes`` → ``text/event-stream``：

- 事件 ``data`` 载荷：``{"type": "quotes_updated", "ts", "count", "quotes": [...]}``
  （quotes 为指数 + 全部自选的快照，字段见 quote_streamer._QUOTE_FIELDS）。
- 每 15s 一条 SSE 注释行（``: keepalive``）防中间层掐空闲连接。
- 客户端断开由 ASGI cancel → generator finally 反注册队列。

零额外依赖：不用 sse-starlette，StreamingResponse + asyncio.Queue 足够。
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

_KEEPALIVE_SECONDS = 15.0


@router.get("/stream/quotes")
async def stream_quotes(request: Request) -> StreamingResponse:
    """订阅实时行情推送（指数 + 自选，快照式全量推送）。"""
    streamer = getattr(request.app.state, "quote_streamer", None)
    if streamer is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="行情推送服务未启动")

    qid, queue = streamer.subscribe()

    async def event_gen():  # type: ignore[no-untyped-def]
        try:
            # 首帧 hello：告诉前端连接可用 + 当前订阅规模
            hello = {"type": "hello", "subscribers": streamer.subscriber_count}
            yield f"data: {json.dumps(hello, ensure_ascii=False)}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            streamer.unsubscribe(qid)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 反代时不缓冲
        },
    )
