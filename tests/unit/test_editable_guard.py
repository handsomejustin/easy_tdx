"""_editable_guard 入口守卫测试：失效态提示 + 正常态转发（#58）。

失效态无法在测试里真实构造（需要破坏 site-packages 的 .pth），用
meta_path 阻断器让 ``easy_tdx.cli`` 的导入抛 ``ModuleNotFoundError``。
"""

from __future__ import annotations

import sys
import types

import pytest

from easy_tdx import _editable_guard


class _CliImportBlocker:
    """meta_path finder：``easy_tdx.cli`` 一律抛 ModuleNotFoundError，其余放行。"""

    def find_spec(self, fullname, path=None, target=None):  # noqa: ARG002
        if fullname == "easy_tdx.cli":
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None


def test_broken_editable_prints_hint_and_exits(capsys, monkeypatch):
    """easy_tdx.cli 不可导入时：打印修复指引并以退出码 1 结束。"""
    # easy_tdx.cli 可能已被 conftest/其他用例真实导入，先清缓存并阻断再次加载，
    # 否则 import 系统直接命中 sys.modules 短路，阻断器根本不会被咨询。
    monkeypatch.delitem(sys.modules, "easy_tdx.cli", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_CliImportBlocker(), *sys.meta_path])

    with pytest.raises(SystemExit) as exc_info:
        _editable_guard.main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "easy_tdx.cli" in err
    # 指引必须点名失效根源与两条修复命令，否则用户无从下手
    assert "_editable_impl_easy_tdx.pth" in err
    assert "pip uninstall easy-tdx -y && pip install -e . --no-deps" in err
    assert "easy_tdx.__path__" in err


def test_healthy_path_forwards_to_click_group(monkeypatch):
    """正常态：main() 直接转发调用 easy_tdx.cli.cli。"""
    called: list[bool] = []

    stub = types.ModuleType("easy_tdx.cli")
    stub.cli = lambda: called.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "easy_tdx.cli", stub)

    _editable_guard.main()

    assert called == [True]
