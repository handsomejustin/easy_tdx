"""实时数据 WebSocket 路由（v1.28 起联动 RealtimeDataFeed）。

``GET /api/v1/ws/realtime/{symbol}``（WebSocket）：

- 连接即订阅 path 上的 symbol（如 ``SZ000001``），服务端开始按需轮询并推送
  tick 帧；连接断开自动退订，无人订阅时完全停止轮询（节能语义与
  ``/stream/quotes`` 的 QuoteStreamer 一致，见 :mod:`easy_tdx.web.realtime_hub`）。
- 服务端推送帧格式（JSON）::

      {"type": "tick", "symbol": "SZ000001", "market": "SZ", "code": "000001",
       "price": 10.5, "volume": 12345.0, "ts": 1760000000.0,
       "open": ..., "high": ..., "low": ..., "pre_close": ..., "amount": ..., "name": "平安银行"}

  空闲时每 30s 一条 ``{"type": "ping"}`` 心跳；连接级错误发
  ``{"type": "error", "msg": ...}``。
- 客户端控制消息（JSON 文本帧）::

      {"action": "subscribe",   "symbol": "SH600000"}
      {"action": "unsubscribe", "symbol": "SH600000"}

  服务端回 ``{"type": "status", "msg": "subscribed SH600000"}`` 确认；
  去重后标的总数上限 80（get_stock_quotes 协议约束），超限回错误帧。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from easy_tdx.web.realtime_hub import RealtimeStreamHub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

#: 空闲心跳间隔（秒）。receive 超时未收到客户端消息即发一条 ping。
_HEARTBEAT_SECONDS = 30.0


async def _pump(websocket: WebSocket, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """唯一的发送协程：把 hub 队列里的帧逐条写给客户端。

    单一写者模型：tick / status / error / ping 全部经队列串行发出，
    避免多协程并发 send_json 的帧交错风险。
    """
    while True:
        frame = await queue.get()
        await websocket.send_json(frame)


@router.websocket("/ws/realtime/{symbol}")
async def realtime_websocket(websocket: WebSocket, symbol: str) -> None:
    """WebSocket 实时行情订阅（协议见模块 docstring）。"""
    await websocket.accept()
    hub: RealtimeStreamHub | None = getattr(websocket.app.state, "realtime_hub", None)
    if hub is None:
        await websocket.send_json(
            {"type": "error", "msg": "实时数据源不可用（MAC 行情客户端未连接）"}
        )
        await websocket.close()
        return

    cid, queue = hub.connect()
    logger.info("WS realtime 连接：symbol=%s cid=%s", symbol, cid)

    def _enqueue(frame: dict[str, Any]) -> None:
        """控制帧也走队列（容量满时静默丢弃，不影响行情流）。"""
        try:
            queue.put_nowait(frame)
        except asyncio.QueueFull:
            pass

    pump_task = asyncio.create_task(_pump(websocket, queue))
    try:
        try:
            await hub.subscribe(cid, symbol)
        except ValueError as exc:
            _enqueue({"type": "error", "msg": str(exc)})
            await websocket.close()
            return

        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                _enqueue({"type": "ping"})
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                _enqueue({"type": "error", "msg": "invalid JSON"})
                continue

            action = str(data.get("action", ""))
            target = str(data.get("symbol", ""))
            if action == "subscribe" and target:
                try:
                    await hub.subscribe(cid, target)
                except ValueError as exc:
                    _enqueue({"type": "error", "msg": str(exc)})
                    continue
                _enqueue({"type": "status", "msg": f"subscribed {target.upper()}"})
            elif action == "unsubscribe" and target:
                await hub.unsubscribe(cid, target)
                _enqueue({"type": "status", "msg": f"unsubscribed {target.upper()}"})
            else:
                _enqueue({"type": "error", "msg": f"unknown action: {raw[:80]}"})

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS realtime 连接异常：symbol=%s", symbol)
    finally:
        pump_task.cancel()
        await asyncio.gather(pump_task, return_exceptions=True)
        await hub.disconnect(cid)
        logger.info("WS realtime 连接关闭：symbol=%s cid=%s", symbol, cid)
