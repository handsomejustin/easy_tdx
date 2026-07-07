# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — 把 easy-tdx + Vue 前端打包成单一 Windows EXE。

构建前提（CI 会自动完成，本地手动构建需自行执行）::

    1. pip install -e ".[web]" pyinstaller
    2. cd web-ui && npm ci && npm run build   # 产出 web-ui/dist/
    3. pyinstaller easy_tdx.spec              # 产出 dist/easy-tdx.exe

设计要点：
- ``--onefile``：单 EXE，老人双击即用。首次启动解压到临时目录需 2-5 秒。
- ``console=False``：无黑窗（Windows GUI 子系统）。
- ``collect_submodules('uvicorn')``：uvicorn 用 importlib 动态加载协议
  实现，PyInstaller 静态分析漏掉会导致启动报 ModuleNotFoundError。
- ``collect_submodules('easy_tdx')``：routers/backtest.strategies 等大量
  延迟 import，全量收集避免遗漏。
- ``web-ui/dist → web_dist``：app.py 的 ``_resolve_web_dist_dir`` 会从
  ``sys._MEIPASS/web_dist`` 读取前端资源。
- ``~/.easy_tdx`` 的 SQLite 不在打包范围（用户运行时写入家目录），无需处理。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports: list[str] = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("easy_tdx")
# pandas / numpy / scipy 由 PyInstaller 自带 hook 处理（见
# PyInstaller/hooks/hook-pandas.* 等），无需手动 collect_submodules——
# 手动全量收集会把 numpy.typing.tests / pandas._numba.kernels 等可选/测试
# 模块也拖进来，既增加体积又制造噪音 WARNING。
# 系统托盘（打包态专用）：pystray 在 Windows 用 win32 API，Pillow 的
# 图像格式插件用 importlib 动态加载，两者都需要显式声明。
hiddenimports += collect_submodules("pystray")

datas: list[tuple[str, str]] = []
datas += collect_data_files("tzdata")
# Pillow 的图像格式插件（PngImagePlugin 等）随数据文件一起收集
datas += collect_data_files("PIL")
# 前端 dist 打包到运行时 sys._MEIPASS/web_dist
datas += [("web-ui/dist", "web_dist")]

block_cipher = None

a = Analysis(
    ["src/easy_tdx/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # matplotlib 仅 CLI 表格输出用，EXE 形态不需要
        "matplotlib",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        # 测试框架不打进生产 EXE
        "pytest",
        "IPython",
        "jupyter",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="easy-tdx",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # GUI 子系统：双击不弹控制台黑窗。排查问题时改 console=True 重新打包。
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/easy-tdx.ico",  # 暂无图标资源；后续补
)
