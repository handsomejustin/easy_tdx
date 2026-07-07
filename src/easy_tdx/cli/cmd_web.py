"""easy-tdx serve — 启动 Web API 服务器。"""

from __future__ import annotations

import threading
import webbrowser

import click


@click.command("serve")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8000, type=int, help="监听端口")
@click.option("--tdx-host", default=None, help="TDX 服务器地址（默认自动选择最优）")
@click.option("--tdx-port", default=None, type=int, help="TDX 服务器端口")
@click.option("--reload", is_flag=True, help="开发模式（自动重载）")
@click.option(
    "--open-browser/--no-open-browser",
    default=True,
    help="启动后自动打开浏览器（默认开启，PyInstaller 打包后老人双击即用）",
)
def serve(
    host: str,
    port: int,
    tdx_host: str | None,
    tdx_port: int | None,
    reload: bool,
    open_browser: bool,
) -> None:
    """启动 Web API 服务器（需要安装 easy-tdx[web]）。"""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "错误：缺少 web 依赖。请运行: pip install easy-tdx[web]",
            err=True,
        )
        raise SystemExit(1) from None

    # 启动后延迟打开浏览器：uvicorn 需要约 1-2 秒绑定端口，过早打开会
    # 命中 connection refused。用后台 Timer 而非阻塞主线程。
    if open_browser and not reload:
        # 0.0.0.0 / 127.0.0.1 在浏览器里用 localhost 打开（更友好）。
        display_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
        url = f"http://{display_host}:{port}"
        # 1.5 秒通常足够本地端口就绪；uvicorn 启动慢的机器可适当延长。
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    if reload:
        uvicorn.run(
            "easy_tdx.web:app_factory",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
    else:
        from easy_tdx.web import create_app

        app = create_app(host=tdx_host, port=tdx_port)
        uvicorn.run(app, host=host, port=port)
