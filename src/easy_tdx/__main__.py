"""``python -m easy_tdx`` 入口 + PyInstaller 打包入口（``easy-tdx.exe``）。

**两种启动形态**：

- **开发态**（``python -m easy_tdx``）：等价于 ``easy-tdx`` CLI，无托盘。
- **打包态**（双击 EXE）：uvicorn 后台线程 + 右下角系统托盘图标，老人右键
  → 退出即可关闭，无需任务管理器。

**三个关键坑（PyInstaller frozen 模式）**：

1. **``console=False`` 下标准流为 None**：Windows GUI 子系统下
   ``sys.stdout`` / ``sys.stderr`` 都是 ``None``。uvicorn 的
   ``DefaultFormatter.__init__`` 会调 ``sys.stderr.isatty()``，对 ``None`` 取
   属性直接报 ``AttributeError: 'NoneType' object has no attribute 'isatty'``，
   导致启动即崩。解决：把 None 流重定向到家目录下的日志文件。

2. **``multiprocessing`` spawn 子进程会重新 import ``__main__``**：Windows
   下 ``ProcessPoolExecutor`` 用 spawn 方式启动子进程，子进程会重新执行
   ``__main__`` 模块来重建执行环境。如果不拦截，子进程会再次执行 ``cli()``
   → 又启动一个 uvicorn server → 子进程死循环 + 抢占端口 + 各种莫名其妙的
   错误。解决：(a) 调 ``freeze_support()``；(b) 在 ``__main__`` 里判断如果是
   子进程（argv 含 ``--multiprocessing-fork`` 等标记）就直接 return，不跑 CLI。
   一键寻优、screen scanner 等所有用多进程的功能都依赖这个保护。

3. **托盘需要主线程消息泵**：pystray 在 Windows 上需要主线程跑消息循环，
   而 uvicorn 的 ``server.run()`` 是阻塞调用。解决：打包态把 uvicorn 挪到
   后台线程，主线程跑托盘（见 ``_run_tray_server`` / ``easy_tdx.tray``）。
   开发态走原 CLI 路径，不引入托盘。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _is_multiprocessing_child() -> bool:
    """判断当前进程是否为 multiprocessing fork 出来的子进程。

    Windows spawn 模式下，子进程的 argv[0] 是父 EXE 路径，但会带特殊 flag：
    ``--multiprocessing-fork``（带或不带 ``=``）或新版 Python 的
    ``--mp-main`` / ``-c`` 等。检测到这些就说明本进程是子进程，不应启动 CLI。
    """
    if len(sys.argv) < 2:
        return False
    first_arg = sys.argv[1]
    # multiprocessing 标准标记（不同 Python 版本略有差异）
    return first_arg.startswith("--multiprocessing-fork") or first_arg == "--mp-main"


def _redirect_std_streams_to_log() -> None:
    """``console=False`` 下把 None 的 stdout/stderr 重定向到日志文件。

    PyInstaller ``--windowed``（Windows GUI 子系统）下 Python 的 sys.stdout /
    sys.stderr 为 ``None``。许多库（uvicorn/click/logging）假设它们存在，
    调 ``.isatty()`` 或 ``.write()`` 即崩。本函数把它们重定向到家目录下的
    ``easy_tdx_runtime.log``，并设 ``PYTHONUNBUFFERED=1`` 保证日志实时落盘。

    只在 ``sys.stdout is None``（打包态）时启用；开发态（有真实终端）不动。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return  # 开发态：有真实终端，不重定向

    # 落在 ~/.easy_tdx/，与 strategy_store 的 SQLite 同目录，便于一键收集诊断
    config_dir = Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))
    config_dir.mkdir(parents=True, exist_ok=True)
    log_path = config_dir / "easy_tdx_runtime.log"

    # 用 "a" 追加而非覆盖：老人多次启动的日志都保留，便于复盘
    try:
        f = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        # 家目录不可写（极罕见），退化到 os.devnull——至少不崩
        f = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f


def _run_tray_server() -> None:
    """打包态双击启动专用：uvicorn（后台线程）+ 系统托盘（主线程）。

    提取为函数避免 ``__main__`` 顶层 import 拖累开发态启动——pystray/Pillow
    只在打包态才需要。
    """
    from easy_tdx.tray import run_with_tray
    from easy_tdx.web import create_app

    run_with_tray(
        app_factory=create_app,
        host="127.0.0.1",
        port=8000,
        open_browser=True,
    )


def main() -> None:
    """进程入口：区分子进程 / 开发态 / 打包态三条路径。"""
    # 1. 必须最先：multiprocessing 子进程保护。
    #    Windows spawn 子进程会重新 import __main__；如果不拦截，子进程会
    #    再次跑 cli() 启动 uvicorn，导致死循环 + 端口冲突 + 数据错乱。
    if _is_multiprocessing_child():
        # 子进程：只跑 freeze_support（处理 multiprocessing 协议），
        # 不启动 CLI / uvicorn / 浏览器。子进程的 mainloop 由
        # multiprocessing 内部接管，会执行被 pickle 过来的任务函数。
        import multiprocessing

        multiprocessing.freeze_support()
        # freeze_support 在子进程里会阻塞到任务完成后 exit，理论不会走到这里；
        # 但防御性 return，避免任何情况下的 CLI 重复启动。
        sys.exit(0)

    # 2. 标准流重定向（必须在 import click/uvicorn 之前）。
    _redirect_std_streams_to_log()

    # 3. freeze_support 即便在主进程也建议调（无害，防御未来加的子进程触发点）。
    import multiprocessing

    multiprocessing.freeze_support()

    from easy_tdx.cli import cli

    is_frozen = getattr(sys, "frozen", False)

    # 双击启动（无参 + 打包态）→ 走托盘路径：uvicorn 后台 + 右下角图标可退出。
    # 命令行带参（含 ``serve``）→ 走原 CLI，行为不变（开发/调试场景）。
    if is_frozen and len(sys.argv) <= 1:
        _run_tray_server()
        return

    # 命令行显式调用：保持原行为。
    # 显式传 ``serve --no-open-browser`` 可关闭浏览器自动打开，
    # 传其他子命令（如 ``server-info``）走原 CLI 行为。
    if len(sys.argv) <= 1:
        # 开发态无参 python -m easy_tdx：默认走 serve（无托盘，开发态不需要）。
        sys.argv = [sys.argv[0], "serve"]

    cli()


if __name__ == "__main__":
    main()
