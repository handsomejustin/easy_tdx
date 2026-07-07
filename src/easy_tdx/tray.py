"""系统托盘（仅打包态使用）。

双击 ``easy-tdx.exe`` 后：uvicorn 跑在后台线程，主线程跑 pystray 托盘
图标，右键菜单提供"打开浏览器 / 退出"。老人不用学任务管理器，右下角
图标右键 → 退出即可干净关闭。

**为什么需要独立模块**：
- uvicorn 的 ``server.run()`` 是阻塞调用。常规 CLI 路径（``cmd_web.py``）
  让 uvicorn 占主线程；但 pystray 在 Windows 上需要主线程的消息泵，所以
  打包态必须把 uvicorn 挪到后台线程。
- 本模块仅在 PyInstaller frozen 模式下由 ``__main__.py`` 调用，开发态
  ``easy-tdx serve`` 走原 CLI 路径，不引入托盘。

依赖：``pystray`` + ``Pillow``（纯 Python wheel，PyInstaller 打包无坑）。
两者仅在打包态 import，开发态不强制安装。
"""

from __future__ import annotations

import logging
import threading
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import PIL

logger = logging.getLogger(__name__)


def _make_icon_image() -> PIL.Image.Image:
    """画一个简单的"K 线图"风格图标（红涨绿跌的简化样式）。

    用 Pillow 代码生成，避免在仓库里维护二进制 .ico 文件。32×32 是
    Windows 系统托盘的标准尺寸。
    """
    from PIL import Image, ImageDraw

    size = 64  # 高分辨率，pystray 会自动缩放到托盘尺寸
    img = Image.new("RGBA", (size, size), (30, 30, 40, 255))  # 深色背景
    draw = ImageDraw.Draw(img)

    # 三根简化 K 线：红涨两根 + 绿跌一根
    bars = [
        # (x, y_top, y_bottom, color) —— y 越大越往下
        (16, 18, 44, (231, 76, 60)),  # 红
        (30, 12, 38, (231, 76, 60)),  # 红（更高的高点）
        (44, 22, 50, (46, 204, 113)),  # 绿
    ]
    for x, top, bottom, color in bars:
        # 影线（细竖线）
        draw.line([(x + 3, top - 4), (x + 3, bottom + 4)], fill=color, width=1)
        # 实体（矩形）
        draw.rectangle([(x, top), (x + 6, bottom)], fill=color)

    return img


def run_with_tray(
    app_factory: Callable[[], Any],
    host: str,
    port: int,
    open_browser: bool = True,
) -> None:
    """启动 uvicorn（后台线程）+ 系统托盘（主线程阻塞）。

    Args:
        app_factory: 返回配置好的 ASGI app 的零参 callable（惰性调用，
            避免本模块顶层 import fastapi/uvicorn）。
        host: 监听地址。
        port: 监听端口。
        open_browser: 启动后是否自动开浏览器。
    """
    import signal

    import uvicorn
    from pystray import Icon, Menu, MenuItem

    app = app_factory()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    # uvicorn 跑在后台线程：server.run() 阻塞，由 server.should_exit 通知退出
    server_thread = threading.Thread(target=server.run, daemon=True, name="uvicorn")
    server_thread.start()

    # 启动后延迟开浏览器（等端口就绪）
    if open_browser:
        display_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
        url = f"http://{display_host}:{port}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    def _open_browser() -> None:
        display_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
        webbrowser.open(f"http://{display_host}:{port}")

    def _quit(icon: Icon, item: MenuItem) -> None:
        logger.info("Tray quit clicked — shutting down uvicorn")
        server.should_exit = True
        icon.stop()

    menu = Menu(
        MenuItem("打开浏览器", _open_browser, default=True),  # default = 双击图标触发
        Menu.SEPARATOR,
        MenuItem("退出", _quit),
    )

    icon = Icon("easy-tdx", _make_icon_image(), "easy-tdx 回测服务", menu)

    # Ctrl+C 兜底（console=False 下其实收不到，但开发态调试时有用）
    def _signal_handler(signum: int, frame: object) -> None:
        server.should_exit = True
        icon.stop()

    try:
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError):
        # 非 main 线程或 Windows GUI 子系统下会失败，可忽略
        pass

    logger.info("Starting tray icon (main thread blocks here)")
    icon.run()  # 阻塞主线程，直到 icon.stop() 被调用

    # 托盘退出后，等 uvicorn 线程收尾（最多 5 秒）
    server_thread.join(timeout=5.0)
    logger.info("uvicorn thread joined — process exiting")
