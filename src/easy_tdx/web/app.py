"""FastAPI application factory and lifespan management."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from easy_tdx.web.errors import register_exception_handlers

logger = logging.getLogger(__name__)


def _resolve_web_dist_dir() -> Path | None:
    """定位前端构建产物目录（Vite build 输出的 ``web-ui/dist``）。

    依次探测四处，命中即返回，全部缺失时返回 ``None``（仅 API 可用，
    前端页面 404）：

    1. ``EASY_TDX_WEB_DIST`` 环境变量——部署/调试时显式指定。
    2. PyInstaller 运行态：``sys._MEIPASS / "web_dist"``——单 EXE 解压
       后的临时目录（``--onefile`` 模式）。开发态无 ``_MEIPASS`` 属性，
       此分支自动跳过。
    3. 开发态：仓库根目录的 ``web-ui/dist``——支持 ``pip install -e .``
       后直接 ``easy-tdx serve`` 调试，无需打包。
    4. PyPI wheel 安装态：包内 ``easy_tdx/web/dist``——hatchling 把
       编译好的 dist 作为数据文件打进 wheel（v1.19.5 起含），让
       ``pip install easy-tdx[web]`` 后开箱即用 web UI。
    """
    env_dir = os.environ.get("EASY_TDX_WEB_DIST")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p

    # PyInstaller --onefile 解压目录（frozen 运行态）
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        p = Path(meipass) / "web_dist"
        if p.is_dir():
            return p

    # 开发态：从 src/easy_tdx/web/app.py 回溯到仓库根的 web-ui/dist
    repo_root = Path(__file__).resolve().parents[3]
    p = repo_root / "web-ui" / "dist"
    if p.is_dir():
        return p

    # PyPI 安装态：包内的 web/dist（wheel 打包时 force-include 进来）
    pkg_dist = Path(__file__).resolve().parent / "dist"
    if pkg_dist.is_dir():
        return pkg_dist

    return None


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

    # --- 实时行情 SSE 推送器（共享轮询 + fan-out） ---
    try:
        from easy_tdx.models.enums import Market
        from easy_tdx.web.quote_streamer import QuoteStreamer
        from easy_tdx.web.watchlist_store import get_watchlist_store

        store = get_watchlist_store()

        async def _watch_symbols() -> list[tuple[Market, str]]:
            # SQLite 存 "SH"/"SZ"/"BJ" 字符串，轮询器需要 Market 枚举
            return [(Market[mkt], code) for mkt, code in store.symbols()]

        streamer = QuoteStreamer(client.get_security_quotes, _watch_symbols)
        streamer.start()
        app.state.quote_streamer = streamer
    except Exception:
        logger.warning("QuoteStreamer 启动失败 — SSE 推送不可用", exc_info=True)
        app.state.quote_streamer = None

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

    # --- 关闭实时行情推送器 ---
    streamer_svc = getattr(app.state, "quote_streamer", None)
    if streamer_svc is not None:
        try:
            await streamer_svc.stop()
        except Exception:
            logger.warning("QuoteStreamer stop failed", exc_info=True)

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
    enable_ui: bool = True,
) -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    Args:
        enable_ui: 是否同源托管 Web UI 前端（``easy-tdx serve --no-ui``
            纯 API 模式传 False：不挂载静态 dist，根路径 404，仅 /api/v1/*）。
    """
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
    from easy_tdx.web.routers.server import router as server_router
    from easy_tdx.web.routers.sina import router as sina_router
    from easy_tdx.web.routers.strategies import router as strategies_router
    from easy_tdx.web.routers.stream import router as stream_router
    from easy_tdx.web.routers.watchlist import router as watchlist_router

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
    # 服务器设置路由（列出/测速/切换 TDX host）
    app.include_router(server_router, prefix="/api/v1")
    # 自选股路由（SQLite 持久化，纯 CRUD，不依赖行情连接）
    app.include_router(watchlist_router, prefix="/api/v1")
    # 实时行情 SSE 路由（依赖 lifespan 里的 QuoteStreamer）
    app.include_router(stream_router, prefix="/api/v1")

    # --- 前端 dist 托管（生产/打包态同源服务，开发态可缺省） ---
    # 必须在所有 API 路由注册之后：StaticFiles(html=True) 挂在 "/" 会吞掉
    # 未匹配路径，放最后保证 /api/v1/* 优先命中路由表。
    # 强制注册 MIME 类型：干净 Windows（无开发环境）的注册表里可能没有
    # .js/.mjs/.css 的 Content Type，导致 mimetypes.guess_type 返回 None，
    # StaticFiles 回退到 text/plain。浏览器的 <script type="module"> 启用
    # 严格 MIME 检查，拒绝执行 text/plain 的 JS → 页面纯黑（v1.19.1 bug）。
    # add_type 会覆盖/补充注册表缺失的映射，无论机器装没装开发工具都生效。
    import mimetypes

    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")

    from fastapi.staticfiles import StaticFiles

    dist_dir = _resolve_web_dist_dir() if enable_ui else None
    if dist_dir is not None:
        # SPA fallback：前端用 createWebHistory（HTML5 history 模式），
        # 用户直接访问 /optimize、/portfolio 等前端路由或刷新时，后端必须
        # 返回 index.html 让 Vue Router 接管，而不是 404。
        # 实现方式：用 StaticFiles 挂在 "/static" 提供真实文件（JS/CSS/图标），
        # 再加一个 catch-all 路由把所有非 /api、非 /static 的 GET 请求导向
        # index.html。但这样会改变 JS/CSS 的 URL 前缀（/assets → /static/assets），
        # 需要改 vite base 配置，代价大。
        # 更简单的方式：先尝试 StaticFiles 服务真实文件，找不到时 fallback。
        # Starlette 的 StaticFiles(html=True) 不做 SPA fallback，故子类化它。
        from pathlib import Path as _Path

        from starlette.responses import FileResponse

        class SPAStaticFiles(StaticFiles):
            """StaticFiles + SPA fallback：404 时返回 index.html。"""

            async def get_response(self, path: str, scope):  # type: ignore[no-untyped-def]
                try:
                    return await super().get_response(path, scope)
                except Exception:
                    # 任何 404（路径非文件）都返回 index.html，让前端路由处理。
                    # 仅对 GET 请求生效；API 路径 (/api/v1/*) 已在前面注册，
                    # 不会走到这里。
                    index = _Path(str(self.directory)) / "index.html"
                    if index.is_file():
                        return FileResponse(str(index))
                    raise

        app.mount("/", SPAStaticFiles(directory=str(dist_dir), html=True), name="web-ui")
        logger.info("Web UI mounted from %s (SPA fallback enabled)", dist_dir)
    else:
        logger.info("Web UI dist not found — serving API only")

    return app
