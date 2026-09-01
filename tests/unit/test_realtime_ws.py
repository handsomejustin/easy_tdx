"""RealtimeStreamHub（WebSocket 实时推送枢纽）单元测试。

全程用假行情客户端（不打真实网络、不受交易时段限制——hub 传 sessions=()），
覆盖：订阅触发轮询、多客户端并发订阅同/不同标的、退订引用计数与竞态、
无人订阅完全停止轮询、背压丢旧、以及 WS 端点端到端帧格式。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from easy_tdx.web.realtime_hub import (
    MAX_WS_SYMBOLS,
    RealtimeStreamHub,
    parse_realtime_symbol,
)

pytest.importorskip("fastapi")


class FakeQuoteClient:
    """假 MAC 行情客户端：每次调用价格/量递增（绕过 feed 的 (price, vol) 去重）。"""

    def __init__(self) -> None:
        self.calls = 0
        self.requested: list[list[tuple[int, str]]] = []
        self._seq = 0

    async def get_stock_quotes(
        self, stocks: list[tuple[int, str]], fields: Any = None
    ) -> pd.DataFrame:
        self.calls += 1
        self.requested.append(list(stocks))
        self._seq += 1
        rows = []
        for market, code in stocks:
            base = 10.0 + (int(code) % 100) * 0.1
            rows.append(
                {
                    "market": int(market),
                    "code": code,
                    "close": base + self._seq * 0.01,
                    "vol": 1000.0 + self._seq,
                    "open": base,
                    "high": base + 1.0,
                    "low": base - 1.0,
                    "pre_close": base,
                    "amount": (base + self._seq * 0.01) * 1000.0,
                    "name": f"股票{code}",
                }
            )
        return pd.DataFrame(rows)


def _make_hub(**kwargs: Any) -> tuple[RealtimeStreamHub, FakeQuoteClient]:
    client = FakeQuoteClient()
    hub = RealtimeStreamHub(
        client,
        interval=0.1,  # feed 内部 clamp 下限
        sessions=(),  # 关闭交易时段过滤，测试不受运行时刻影响
        **kwargs,
    )
    return hub, client


async def _next_tick(queue: asyncio.Queue[dict[str, Any]], timeout: float = 5.0) -> dict[str, Any]:
    """取队列里的下一帧（跳过 status/ping 等控制帧）。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        assert remaining > 0, "等待 tick 帧超时"
        frame = await asyncio.wait_for(queue.get(), timeout=remaining)
        if frame.get("type") == "tick":
            return frame


# ── 符号解析 ─────────────────────────────────────────────────────────────────


def test_parse_symbol() -> None:
    assert parse_realtime_symbol("SZ000001") == (0, "000001")
    assert parse_realtime_symbol("sh600519") == (1, "600519")
    assert parse_realtime_symbol("BJ920002") == (2, "920002")
    for bad in ("600519", "XX000001", "SZ00001a", "SZ0000001", ""):
        with pytest.raises(ValueError, match="标的格式"):
            parse_realtime_symbol(bad)


# ── 订阅 / 轮询生命周期 ──────────────────────────────────────────────────────


async def test_subscribe_starts_polling_and_pushes_frames() -> None:
    """订阅 → feed 开始轮询 → 队列收到 {symbol, price, ts} tick 帧。"""
    hub, client = _make_hub()
    assert not hub.polling  # 无人订阅不轮询

    cid, queue = hub.connect()
    await hub.subscribe(cid, "SZ000001")
    assert hub.polling
    assert hub.poll_symbols == ["SZ000001"]

    frame = await _next_tick(queue)
    assert frame["type"] == "tick"
    assert frame["symbol"] == "SZ000001"
    assert frame["market"] == "SZ"
    assert frame["code"] == "000001"
    assert frame["price"] > 0
    assert frame["ts"] > 0
    assert frame["name"] == "股票000001"

    # 第二帧（假客户端价格递增，绕过去重）
    frame2 = await _next_tick(queue)
    assert frame2["price"] != frame["price"]
    assert client.calls >= 2

    await hub.shutdown()


async def test_unsubscribe_last_client_stops_polling() -> None:
    """退订到无人订阅 → 轮询完全停止（节能语义）。"""
    hub, client = _make_hub()
    cid, queue = hub.connect()
    await hub.subscribe(cid, "SH600519")
    await _next_tick(queue)
    calls_before = client.calls

    await hub.unsubscribe(cid, "SH600519")
    await asyncio.sleep(0.35)  # 越过若干个 interval，确认不再发起新轮询
    assert not hub.polling
    assert hub.poll_symbols == []
    assert client.calls == calls_before

    await hub.shutdown()


# ── 多客户端并发 ─────────────────────────────────────────────────────────────


async def test_multiple_clients_same_symbol_all_receive() -> None:
    """两个客户端订阅同一标的：都收到推送；退订一个后轮询继续（引用计数）。"""
    hub, client = _make_hub()
    cid1, q1 = hub.connect()
    cid2, q2 = hub.connect()
    await hub.subscribe(cid1, "SZ000001")
    await hub.subscribe(cid2, "sz000001")  # 大小写归一到同一标的

    f1 = await _next_tick(q1)
    f2 = await _next_tick(q2)
    assert f1["symbol"] == f2["symbol"] == "SZ000001"
    # 去重后只轮询一份
    assert hub.poll_symbols == ["SZ000001"]

    # 客户端 1 断开：客户端 2 仍在订阅，轮询不停止
    await hub.disconnect(cid1)
    await asyncio.sleep(0.2)
    assert hub.polling
    await _next_tick(q2)

    await hub.shutdown()


async def test_clients_different_symbols_no_cross_delivery() -> None:
    """不同客户端订阅不同标的：各自只收到自己标的的帧。"""
    hub, _client = _make_hub()
    cid_a, q_a = hub.connect()
    cid_b, q_b = hub.connect()
    await hub.subscribe(cid_a, "SZ000001")
    await hub.subscribe(cid_b, "SH600519")
    assert hub.poll_symbols == ["SH600519", "SZ000001"]  # 排序确定

    for _ in range(3):  # 多收几帧确认无串扰
        fa = await _next_tick(q_a)
        fb = await _next_tick(q_b)
        assert fa["symbol"] == "SZ000001"
        assert fb["symbol"] == "SH600519"

    await hub.shutdown()


async def test_dynamic_subscribe_extends_poll_set() -> None:
    """运行中追加订阅：新标的进入轮询集合并开始推送。"""
    hub, client = _make_hub()
    cid, queue = hub.connect()
    await hub.subscribe(cid, "SZ000001")
    await _next_tick(queue)

    await hub.subscribe(cid, "SH600519")
    assert hub.poll_symbols == ["SH600519", "SZ000001"]
    seen: set[str] = set()
    for _ in range(8):
        frame = await _next_tick(queue)
        seen.add(frame["symbol"])
        if seen == {"SZ000001", "SH600519"}:
            break
    assert seen == {"SZ000001", "SH600519"}
    # 每轮轮询带全量订阅集合（requested 记录 (market_int, code) 元组）
    requested_keys = {f"SZ{c}" if m == 0 else f"SH{c}" for m, c in client.requested[-1]}
    assert {"SZ000001", "SH600519"}.issubset(requested_keys)

    await hub.shutdown()


# ── 竞态 ─────────────────────────────────────────────────────────────────────


async def test_concurrent_subscribe_unsubscribe_race() -> None:
    """多客户端并发订阅/退订同一批标的：最终引用计数与轮询状态一致。"""
    hub, _client = _make_hub()
    cids = [hub.connect()[0] for _ in range(8)]
    symbols = ["SZ000001", "SH600519", "SZ399006"]

    # 并发混订：偶数客户端先订后退，奇数只订
    await asyncio.gather(
        *[hub.subscribe(cid, sym) for cid in cids for sym in symbols],
        *[hub.unsubscribe(cid, sym) for cid in cids[::2] for sym in symbols],
    )
    # 奇数客户端（索引 1,3,5,7）仍各持有 3 个标的的订阅
    assert hub.poll_symbols == sorted(symbols)
    assert hub.subscriber_count == 8

    # 全部断开（并发）→ 轮询停止
    await asyncio.gather(*[hub.disconnect(cid) for cid in cids])
    await asyncio.sleep(0.2)
    assert not hub.polling
    assert hub.poll_symbols == []

    await hub.shutdown()


async def test_symbol_cap_rejected() -> None:
    """去重后标的数超 80（协议上限）拒绝并抛 ValueError。"""
    hub, _client = _make_hub()
    cid, _queue = hub.connect()
    for i in range(MAX_WS_SYMBOLS):
        await hub.subscribe(cid, f"SH{i:06d}")
    with pytest.raises(ValueError, match="上限"):
        await hub.subscribe(cid, "SZ000001")
    await hub.shutdown()


async def test_backpressure_drops_oldest() -> None:
    """队列满时丢最旧保最新（行情快照旧帧无价值）。"""
    hub, _client = _make_hub(queue_size=2)
    cid, queue = hub.connect()
    await hub.subscribe(cid, "SZ000001")

    # 不消费，等队列塞满并溢出
    await asyncio.sleep(0.8)
    assert queue.qsize() <= 2
    prices = [queue.get_nowait()["price"] for _ in range(queue.qsize())]
    # 留下的是最新帧（假客户端价格单调递增）
    assert prices == sorted(prices)

    await hub.shutdown()


# ── WS 端点端到端（TestClient）───────────────────────────────────────────────


def test_ws_endpoint_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接 → 收 tick 帧（真实路由 + hub + feed，仅行情源为假）。

    hub 的 feed 任务跑在 TestClient 的 portal 事件循环里，客户端退出时随循环
    一并销毁，无需（也无法）在测试协程里再 shutdown。
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers.realtime import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    hub, _client = _make_hub()
    app.state.realtime_hub = hub

    with TestClient(app) as client, client.websocket_connect("/api/v1/ws/realtime/SZ000001") as ws:
        frame = ws.receive_json()
        assert frame["type"] == "tick"
        assert frame["symbol"] == "SZ000001"
        assert {"price", "ts", "market", "code"} <= set(frame)
