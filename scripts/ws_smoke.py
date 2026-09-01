"""ws_smoke — WebSocket 实时行情推送手动冒烟脚本（v1.28）。

连 ``/api/v1/ws/realtime/{symbol}``，打印收到的每一帧，验证
RealtimeDataFeed → EventBus → RealtimeStreamHub 的推送链路。

用法::

    # 真实服务器（需 MAC 行情可达且在交易时段，或标的盘外有静止快照）
    .venv/Scripts/python.exe scripts/ws_smoke.py --symbol SZ000001

    # mock 模式（推荐本地冒烟：合成行情、不受交易时段限制）
    # 终端 1：
    EASY_TDX_E2E_MOCK=1 .venv/Scripts/python.exe -m easy_tdx serve --port 8000 --no-open-browser
    # 终端 2：
    .venv/Scripts/python.exe scripts/ws_smoke.py --url ws://127.0.0.1:8000/api/v1/ws/realtime/SZ000001

可选参数：--duration 秒数（默认 15）、--extra-symbol 运行中追加订阅的标的。
退出码：收到至少一帧 tick = 0，否则 1。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import websockets


async def main() -> int:
    parser = argparse.ArgumentParser(description="WebSocket 实时行情冒烟")
    parser.add_argument(
        "--url",
        default="ws://127.0.0.1:8000/api/v1/ws/realtime/SZ000001",
        help="WS 端点（默认本地 serve 的 SZ000001）",
    )
    parser.add_argument("--duration", type=float, default=15.0, help="冒烟时长（秒）")
    parser.add_argument(
        "--extra-symbol", default="SH600519", help="运行中追加订阅的标的（演示动态订阅）"
    )
    args = parser.parse_args()

    ticks = 0
    start = time.perf_counter()

    try:
        async with websockets.connect(args.url) as ws:
            print(f"已连接 {args.url}，监听 {args.duration:.0f}s（Ctrl+C 提前退出）")
            # 3 秒后演示动态订阅（应收到 status 确认 + 新标的 tick）
            subscribe_at = start + 3.0

            async def _maybe_subscribe() -> None:
                if time.perf_counter() < subscribe_at:
                    await asyncio.sleep(subscribe_at - time.perf_counter())
                await ws.send(json.dumps({"action": "subscribe", "symbol": args.extra_symbol}))
                print(f"→ 已发送动态订阅：{args.extra_symbol}")

            sub_task = asyncio.create_task(_maybe_subscribe())
            try:
                while time.perf_counter() - start < args.duration:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    frame = json.loads(raw)
                    if frame.get("type") == "tick":
                        ticks += 1
                        print(
                            f"[tick] {frame['symbol']} 价={frame['price']:.2f} "
                            f"量={frame.get('volume', 0):.0f} 名={frame.get('name', '')} "
                            f"ts={frame['ts']:.0f}"
                        )
                    else:
                        print(f"[{frame.get('type')}] {frame}")
            finally:
                sub_task.cancel()
                await asyncio.gather(sub_task, return_exceptions=True)
    except (OSError, TimeoutError) as exc:
        print(f"连接失败：{exc}\n请确认 serve 已启动（easy-tdx serve）", file=sys.stderr)
        return 1

    print(f"—— 冒烟结束：共收到 {ticks} 帧 tick ——")
    return 0 if ticks > 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
