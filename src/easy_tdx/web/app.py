"""FastAPI application factory and lifespan management."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from easy_tdx.web.errors import register_exception_handlers

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """管理 TDX 连接生命周期：启动时连接，关闭时断开。"""
    from easy_tdx.client import AsyncTdxClient

    # --- 标准 TDX 客户端 ---
    host = app.state.tdx_host
    port = app.state.tdx_port
    timeout = app.state.tdx_timeout

    client = AsyncTdxClient(host=host, port=port, timeout=timeout)
    try:
        await client.connect()
        logger.info("TDX client connected to %s:%s", host, port)
    except Exception:
        logger.warning("TDX client connection failed — endpoints will return 503")

    app.state.tdx_client = client

    # --- MAC 协议客户端 ---
    mac_client = None
    enable_mac = getattr(app.state, "enable_mac", True)
    if enable_mac:
        try:
            from easy_tdx.mac.client import AsyncMacClient

            mac_client = AsyncMacClient.from_best_host()
            await mac_client.connect()
            logger.info("MAC client connected")
        except Exception:
            logger.warning("MAC client connection failed — MAC endpoints will return 503")
            mac_client = None
    app.state.mac_client = mac_client

    # --- 扩展市场客户端（可选） ---
    ex_client = None
    enable_ex = getattr(app.state, "enable_ex", False)
    if enable_ex:
        try:
            from easy_tdx.ex.client import AsyncExTdxClient

            ex_client = AsyncExTdxClient.from_best_host()
            await ex_client.connect()
            logger.info("Ex market client connected")
        except Exception:
            logger.warning("Ex market client connection failed — Ex endpoints will return 503")
            ex_client = None
    app.state.ex_client = ex_client

    yield

    # --- 依次关闭 ---
    for name, cli in [
        ("Ex market client", ex_client),
        ("MAC client", mac_client),
        ("TDX client", client),
    ]:
        if cli is not None:
            try:
                await cli.close()
                logger.info("%s disconnected", name)
            except Exception:
                pass

    # --- 关闭回测任务执行器（取消 pending，等待 running） ---
    # shutdown 是同步阻塞调用，包在 to_thread 里避免阻塞 event loop
    import asyncio

    try:
        from easy_tdx.web.task_runner import shutdown_runner

        await asyncio.to_thread(shutdown_runner)
        logger.info("Backtest task runner shutdown")
    except Exception:
        logger.warning("Backtest task runner shutdown failed", exc_info=True)


def _create_app(
    host: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
    *,
    enable_mac: bool = True,
    enable_ex: bool = False,
) -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    from easy_tdx.config import get_best_host, get_port, get_timeout

    if host is None:
        host = get_best_host()
    if port is None:
        port = get_port()
    if timeout is None:
        timeout = get_timeout()

    app = FastAPI(
        title="easy-tdx API",
        description="通达信行情数据 REST + WebSocket API",
        version="1.0.0",
        lifespan=lifespan,
        redoc_url=None,  # 手动注册 redoc 端点以控制 JS CDN URL
    )

    # 手动注册 ReDoc 端点，使用固定版本的 JS（默认 redoc@next 已 404）
    from fastapi.openapi.docs import get_redoc_html

    @app.get("/redoc", include_in_schema=False)
    async def redoc_html() -> Any:
        return get_redoc_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=app.title + " - ReDoc",
            redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@2.2.0/bundles/redoc.standalone.js",
        )

    # Store connection config in app.state for lifespan to use
    app.state.tdx_host = host
    app.state.tdx_port = port
    app.state.tdx_timeout = timeout
    app.state.tdx_client = None  # will be set in lifespan
    app.state.mac_client = None
    app.state.ex_client = None
    app.state.enable_mac = enable_mac
    app.state.enable_ex = enable_ex

    # CORS middleware (permissive for development)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register exception handlers
    register_exception_handlers(app)

    # Mount routers
    from easy_tdx.web.routers.announcement import router as announcement_router
    from easy_tdx.web.routers.backtest import router as backtest_router
    from easy_tdx.web.routers.bars import router as bars_router
    from easy_tdx.web.routers.block import router as block_router
    from easy_tdx.web.routers.board_mac import router as board_mac_router
    from easy_tdx.web.routers.chanlun import router as chanlun_router
    from easy_tdx.web.routers.ex_market import router as ex_market_router
    from easy_tdx.web.routers.finance import router as finance_router
    from easy_tdx.web.routers.indicator import router as indicator_router
    from easy_tdx.web.routers.mac_data import router as mac_data_router
    from easy_tdx.web.routers.mac_quotes import router as mac_quotes_router
    from easy_tdx.web.routers.market import router as market_router
    from easy_tdx.web.routers.realtime import router as realtime_router
    from easy_tdx.web.routers.sina import router as sina_router
    from easy_tdx.web.routers.strategies import router as strategies_router

    app.include_router(market_router, prefix="/api/v1")
    app.include_router(bars_router, prefix="/api/v1")
    app.include_router(finance_router, prefix="/api/v1")
    app.include_router(block_router, prefix="/api/v1")
    app.include_router(chanlun_router, prefix="/api/v1")
    app.include_router(realtime_router, prefix="/api/v1")
    # MAC 协议路由
    app.include_router(board_mac_router, prefix="/api/v1")
    app.include_router(mac_data_router, prefix="/api/v1")
    app.include_router(mac_quotes_router, prefix="/api/v1")
    # 扩展市场路由
    app.include_router(ex_market_router, prefix="/api/v1")
    # 技术指标路由
    app.include_router(indicator_router, prefix="/api/v1")
    # 公告检索路由（巨潮资讯网，独立数据源）
    app.include_router(announcement_router, prefix="/api/v1")
    # 新浪财报三表路由（独立数据源）
    app.include_router(sina_router, prefix="/api/v1")
    # 回测路由（纯计算，不依赖行情连接 lifespan）
    app.include_router(backtest_router, prefix="/api/v1")
    # 策略库路由（SQLite 持久化，纯数据 CRUD）
    app.include_router(strategies_router, prefix="/api/v1")

    return app
