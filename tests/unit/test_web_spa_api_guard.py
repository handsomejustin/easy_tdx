"""SPA fallback 的 /api 守卫测试（v1.29）。

背景（实测踩坑）：未注册的 ``/api/*`` 路径会掉进 StaticFiles 的 SPA
fallback 返回 200 + index.html——前端 ``resp.ok`` 为 true、``resp.json()``
抛 ``Unexpected token '<'``，把"服务是旧版本/端点不存在"伪装成前端解析
错误。守护：未知 /api 路径必须返回 JSON 404，前端路由路径仍回 index.html。
"""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def _make_app_with_ui(tmp_path: Path):
    """带假前端 dist 的 app（index.html + 一个资产文件）。"""
    from easy_tdx.web.app import _create_app

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>spa</title>", encoding="utf-8")
    (dist / "test-asset.txt").write_text("asset", encoding="utf-8")

    import easy_tdx.web.app as app_mod

    original = app_mod._resolve_web_dist_dir
    app_mod._resolve_web_dist_dir = lambda: dist  # type: ignore[assignment]
    try:
        return _create_app(enable_mac=False, enable_ui=True)
    finally:
        app_mod._resolve_web_dist_dir = original  # type: ignore[assignment]


@pytest.fixture()
def client(tmp_path):
    app = _make_app_with_ui(tmp_path)
    with fastapi_testclient.TestClient(app) as c:
        yield c


def test_unknown_api_path_returns_json_404(client):
    """未注册的 /api 路径：JSON 404，绝不能是 200 HTML（SPA fallback）。"""
    resp = client.get("/api/v1/llm/config-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    assert "<!doctype" not in resp.text.lower()


def test_unknown_api_post_returns_404_not_html(client):
    resp = client.post("/api/v1/no-such-endpoint", json={})
    assert resp.status_code in (404, 405)
    assert "<!doctype" not in resp.text.lower()


def test_spa_route_still_serves_index(client):
    """前端路由路径（如 /llm）仍回 index.html（SPA 刷新场景）。"""
    resp = client.get("/llm")
    assert resp.status_code == 200
    assert "spa" in resp.text


def test_static_asset_served(client):
    assert client.get("/test-asset.txt").text == "asset"


def test_registered_api_route_unaffected(client):
    """已注册端点正常返回 JSON（守卫只拦未匹配路径）。"""
    resp = client.get("/api/v1/market/session")
    assert resp.status_code == 200
    assert resp.json()["session_desc"]


def test_index_html_no_store(client):
    """入口 index.html 永远 no-store：防浏览器缓存旧资源引用（强刷仍见旧版）。"""
    for path in ("/", "/llm", "/ai-history"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-store", path
    # 哈希文件名的静态资产不受影响（默认缓存语义）
    asset = client.get("/test-asset.txt")
    assert asset.headers.get("cache-control") != "no-store"
