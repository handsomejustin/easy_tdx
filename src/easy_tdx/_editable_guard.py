"""easy-tdx 控制台入口守卫——可编辑安装失效时给出可操作的修复指引。

背景（#58）：``pip install -e .``（hatchling 可编辑安装）会在 site-packages
留下两样东西：

1. ``_editable_impl_easy_tdx.pth`` —— 内容是仓库 ``src/`` 目录的**绝对路径**，
   Python 靠它把 clone 的源码挂进 ``sys.path``；
2. 一个真实的 ``easy_tdx/`` 目录（pyproject 的 ``force-include`` 把
   ``web-ui/dist`` 前端产物映射进来），**没有 ``__init__.py``**，是 PEP 420
   命名空间包的一个"碎片"。

当仓库目录被移动/重命名/重新 clone、或 .pth 丢失时，``src/`` 从
``sys.path`` 消失，但碎片目录还在：``import easy_tdx`` 依旧成功（解析为
只剩静态资源的命名空间包），``import easy_tdx.cli`` 才失败——pip 生成的
控制台脚本会把 ``ModuleNotFoundError: No module named 'easy_tdx.cli'``
原样抛出，用户完全无法定位。

本模块的存活机制：它同时通过 ``force-include`` 被复制进 site-packages 的
碎片目录。失效态下 ``src/`` 里的代码一行都不可达，唯独这份副本仍可导入，
``easy-tdx`` 入口指向这里的 :func:`main`，就能在坏掉时打印修复指引。
"""

from __future__ import annotations

import sys

_HINT = """\
easy-tdx: 无法导入 easy_tdx.cli —— 可编辑安装（pip install -e .）的注册信息很可能已失效。

可编辑安装在 site-packages 生成 _editable_impl_easy_tdx.pth，内容是仓库 src/ 目录的
绝对路径。仓库目录被移动/重命名/重新 clone，或该文件丢失后，easy_tdx 只剩
site-packages 里的静态资源碎片，源码全部不可达（所以 easy_tdx 本体仍能导入，
偏偏 cli 导不进来）。

排查：
    python -c "import easy_tdx; print(easy_tdx.__path__)"
    # 正常应包含你仓库的 src/easy_tdx 绝对路径；只剩 site-packages 路径即失效

修复（无需删除重建虚拟环境）：
    pip uninstall easy-tdx -y && pip install -e . --no-deps

若以上排查不符合你的情况，请带报错提 issue：
    https://github.com/handsomejustin/easy_tdx/issues
"""


def main() -> None:
    """``easy-tdx`` 控制台入口：转发到 click 组；导入失败时打印修复指引。"""
    try:
        from .cli import cli
    except ModuleNotFoundError:
        print(_HINT, file=sys.stderr)
        raise SystemExit(1) from None
    cli()
