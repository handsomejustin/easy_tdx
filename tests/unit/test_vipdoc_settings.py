"""vipdoc 路径设置（app_settings_store + /settings/vipdoc 端点）单测。

覆盖：KV 存取/删除、端点保存校验（不存在路径 400）、保存后清空涨停缓存、
_effective_vipdoc 优先级（显式参数 > 已存设置 > 自动检测）。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def settings_env(tmp_path, monkeypatch):
    """独立配置目录 + 全新单例。"""
    from easy_tdx.web import app_settings_store as asm

    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path / "cfg"))
    asm._store = None
    yield asm
    asm._store = None


def test_settings_kv_roundtrip(settings_env):
    store = settings_env.get_app_settings_store()
    assert store.get("vipdoc") is None  # 缺省 None
    store.set("vipdoc", r"D:\new_tdx\vipdoc")
    assert store.get("vipdoc") == r"D:\new_tdx\vipdoc"
    store.set("vipdoc", r"E:\tdx\vipdoc")  # 覆盖
    assert store.get("vipdoc") == r"E:\tdx\vipdoc"
    store.delete("vipdoc")
    assert store.get("vipdoc") is None


def test_vipdoc_settings_endpoints(settings_env, tmp_path):
    """GET/PUT 往返；PUT 校验目录存在；保存即清空涨停扫描缓存。"""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.web.errors import register_exception_handlers
    from easy_tdx.web.routers import market as market_mod

    real_dir = tmp_path / "vipdoc_real"
    (real_dir / "sh" / "lday").mkdir(parents=True)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(market_mod.router, prefix="/api/v1")
    app.state.tdx_client = object()

    with TestClient(app) as client:
        # 初始：无已存设置
        r = client.get("/api/v1/settings/vipdoc")
        assert r.status_code == 200
        assert r.json()["stored"] is None

        # 不存在的路径 → 400
        bad = client.put("/api/v1/settings/vipdoc", json={"path": str(tmp_path / "nope")})
        assert bad.status_code == 400

        # 保存有效目录 → 生效 + 涨停缓存清空
        r = client.put("/api/v1/settings/vipdoc", json={"path": str(real_dir)})
        assert r.status_code == 200
        assert r.json()["stored"] == str(real_dir)
        assert market_mod._limitup_cache is None

        # GET 回读
        assert client.get("/api/v1/settings/vipdoc").json()["stored"] == str(real_dir)

        # 清除（空串）→ 恢复自动检测
        r = client.put("/api/v1/settings/vipdoc", json={"path": ""})
        assert r.status_code == 200
        assert client.get("/api/v1/settings/vipdoc").json()["stored"] is None


def test_effective_vipdoc_priority(settings_env, tmp_path, monkeypatch):
    """显式参数 > 已存设置 > 自动检测（None）。"""
    from easy_tdx.web.app_settings_store import get_app_settings_store
    from easy_tdx.web.routers.market import _effective_vipdoc

    get_app_settings_store().set("vipdoc", str(tmp_path))
    assert _effective_vipdoc(str(tmp_path / "other")) == str(tmp_path / "other")  # 显式优先
    assert _effective_vipdoc(None) == str(tmp_path)  # 已存设置
    get_app_settings_store().delete("vipdoc")
    assert _effective_vipdoc(None) is None  # 落回自动检测
