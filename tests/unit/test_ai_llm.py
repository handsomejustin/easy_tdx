"""LLM 客户端与配置单元测试（ai/llm.py，v1.29）。

覆盖：配置文件读写、环境变量兜底、Provider 预设补齐、api_key 脱敏、
未配置 key 的友好报错、openai/anthropic 两种协议的请求组装与响应解析
（HTTP 层 monkeypatch，零真实网络调用）。
"""

from __future__ import annotations

import asyncio

import pytest

from easy_tdx.ai import llm as llm_mod
from easy_tdx.ai.llm import (
    PROVIDER_PRESETS,
    LlmClient,
    LlmConfig,
    LlmError,
    load_config,
    mask_key,
    resolve_config,
    save_config,
)


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path))
    # 清掉可能存在的兜底环境变量，保证用例间互不干扰
    for var in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


class TestConfigFile:
    def test_default_when_no_file(self, config_dir):
        cfg = load_config()
        assert cfg.provider == "deepseek" and cfg.api_key == ""

    def test_save_and_load_roundtrip(self, config_dir):
        save_config(LlmConfig(provider="zhipu", api_key="sk-test1234567890", model="glm-4.6"))
        cfg = load_config()
        assert cfg.provider == "zhipu"
        assert cfg.api_key == "sk-test1234567890"
        assert cfg.model == "glm-4.6"

    def test_corrupt_file_returns_default(self, config_dir):
        (config_dir / "llm.json").write_text("{not json", encoding="utf-8")
        assert load_config().provider == "deepseek"  # 不抛异常

    def test_env_fills_missing_fields(self, config_dir, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "kimi")
        monkeypatch.setenv("LLM_API_KEY", "sk-env-key-123456")
        cfg = load_config()
        assert cfg.provider == "kimi" and cfg.api_key == "sk-env-key-123456"

    def test_file_overrides_env(self, config_dir, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-env")
        save_config(LlmConfig(provider="deepseek", api_key="sk-file-12345678"))
        assert load_config().api_key == "sk-file-12345678"


class TestResolve:
    def test_preset_fills_url_and_model(self, config_dir):
        save_config(LlmConfig(provider="qwen"))
        r = resolve_config()
        assert r.api_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        assert r.model == "qwen-plus"

    def test_explicit_values_win(self, config_dir):
        save_config(LlmConfig(provider="deepseek", api_url="http://gw.local/v1", model="my-model"))
        r = resolve_config()
        assert r.api_url == "http://gw.local/v1" and r.model == "my-model"

    def test_custom_requires_url_and_model(self, config_dir):
        with pytest.raises(ValueError, match="不完整"):
            resolve_config(LlmConfig(provider="custom"))


class TestMaskKey:
    def test_mask(self):
        assert mask_key("") == ""
        assert mask_key("short") == "*****"
        assert mask_key("sk-abcdef1234567890") == "sk-***7890"


class TestClient:
    def test_missing_key_friendly_error(self, config_dir):
        client = LlmClient(LlmConfig(provider="deepseek", api_key=""))
        with pytest.raises(LlmError, match="API Key"):
            asyncio.run(client.chat("hi"))

    def test_ollama_needs_no_key(self, config_dir, monkeypatch):
        captured = {}

        def fake_post(url, headers, payload, timeout):
            captured.update(url=url, headers=headers, payload=payload)
            return {"choices": [{"message": {"content": "OK"}}]}

        monkeypatch.setattr(llm_mod, "_post_json", fake_post)
        client = LlmClient(LlmConfig(provider="ollama", timeout=5))
        reply = asyncio.run(client.chat("ping"))
        assert reply == "OK"
        assert captured["url"].startswith("http://localhost:11434/v1/chat/completions")
        assert "Authorization" not in captured["headers"]  # 免 key 不带鉴权头

    def test_openai_style_request_and_parse(self, config_dir, monkeypatch):
        captured = {}

        def fake_post(url, headers, payload, timeout):
            captured.update(url=url, headers=headers, payload=payload)
            return {"choices": [{"message": {"content": "解读完成"}}]}

        monkeypatch.setattr(llm_mod, "_post_json", fake_post)
        client = LlmClient(LlmConfig(provider="zhipu", api_key="sk-zhipu-123456789"))
        reply = asyncio.run(client.chat("报告…", system_prompt="SYS"))
        assert reply == "解读完成"
        assert captured["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        assert captured["headers"]["Authorization"] == "Bearer sk-zhipu-123456789"
        msgs = captured["payload"]["messages"]
        assert msgs[0] == {"role": "system", "content": "SYS"}
        assert msgs[1]["content"] == "报告…"
        assert captured["payload"]["model"] == "glm-4-flash"

    def test_anthropic_style_request_and_parse(self, config_dir, monkeypatch):
        captured = {}

        def fake_post(url, headers, payload, timeout):
            captured.update(url=url, headers=headers, payload=payload)
            return {"content": [{"type": "text", "text": "Claude 回复"}]}

        monkeypatch.setattr(llm_mod, "_post_json", fake_post)
        client = LlmClient(LlmConfig(provider="claude", api_key="sk-ant-123456789"))
        reply = asyncio.run(client.chat("hi"))
        assert reply == "Claude 回复"
        assert captured["url"] == "https://api.anthropic.com/v1/messages"
        assert captured["headers"]["x-api-key"] == "sk-ant-123456789"
        assert captured["headers"]["anthropic-version"] == "2023-06-01"
        assert captured["payload"]["system"]  # system 走顶层字段而非 messages

    def test_http_error_wrapped(self, config_dir, monkeypatch):
        """_post_json 把 HTTPError（带响应体）包装成带状态码的 LlmError。"""
        import io
        import urllib.error

        def fake_urlopen(req, timeout):
            body = io.BytesIO(b'{"error":"bad key"}')
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", hdrs=None, fp=body
            )

        monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(LlmError, match="401") as ei:
            llm_mod._post_json("https://x/v1/chat/completions", {}, {"m": 1}, 5.0)
        assert ei.value.status == 401
        assert "bad key" in str(ei.value)

    def test_test_endpoint_reports_failure(self, config_dir):
        client = LlmClient(LlmConfig(provider="deepseek", api_key=""))
        result = asyncio.run(client.test())
        assert result["ok"] is False and "API Key" in result["error"]


def test_provider_presets_cover_major_vendors():
    vendors = [
        "deepseek", "qwen", "zhipu", "kimi", "minimax",
        "openai", "claude", "ollama", "custom",
    ]
    for pid in vendors:
        assert pid in PROVIDER_PRESETS, pid
    assert PROVIDER_PRESETS["claude"].api_style == "anthropic"
    assert PROVIDER_PRESETS["ollama"].needs_key is False
    assert PROVIDER_PRESETS["zhipu"].base_url.startswith("https://open.bigmodel.cn")


class TestTimeoutSemantics:
    def test_default_timeout_is_generous(self):
        """默认超时 ≥120s：非流式接口需等模型生成完整段回复（大报告 1-3 分钟）。"""
        assert LlmConfig().timeout >= 120

    def test_read_timeout_actionable_message(self, monkeypatch):
        """读超时单独成类报错，文案给出「调大超时」动作而非裸异常。"""

        def fake_urlopen(req, timeout):
            raise TimeoutError("The read operation timed out")

        monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(LlmError, match="请求超时（180s"):
            llm_mod._post_json("https://x/v1/chat/completions", {}, {"m": 1}, 180.0)

    def test_connect_timeout_via_urlerror(self, monkeypatch):
        """连接期超时（URLError.reason=TimeoutError）同样走超时文案。"""
        import urllib.error

        def fake_urlopen(req, timeout):
            raise urllib.error.URLError(TimeoutError("timed out"))

        monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(LlmError, match="请求超时"):
            llm_mod._post_json("https://x/v1/chat/completions", {}, {"m": 1}, 30.0)


class TestAsyncChatTask:
    """POST /llm/chat/async + GET /llm/chat/tasks/{id} 的提交-轮询闭环。"""

    @pytest.fixture(autouse=True)
    def _fresh_history_store(self, config_dir):
        """每个用例用独立的 llm_history.db（模块级单例绑定了首个用例的临时目录）。"""
        import easy_tdx.web.llm_history_store as hs

        hs._store = None
        yield
        hs._store = None

    def test_submit_and_poll_done(self, config_dir, monkeypatch):
        import time

        from fastapi.testclient import TestClient

        from easy_tdx.web.app import _create_app

        def fake_chat(self, prompt, system_prompt=None):
            async def _slow():
                await asyncio.sleep(0.05)
                return f"解读:{prompt[:8]}"
            return _slow()

        monkeypatch.setattr(LlmClient, "chat", fake_chat)
        app = _create_app(enable_mac=False, enable_ui=False)
        with TestClient(app) as c:
            r = c.post("/api/v1/llm/chat/async", json={"prompt": "整份回测报告…" * 10})
            assert r.status_code == 202, r.text
            task_id = r.json()["task_id"]
            assert r.json()["status"] in ("pending", "running")

            state = None
            for _ in range(50):
                state = c.get(f"/api/v1/llm/chat/tasks/{task_id}").json()
                if state["status"] in ("done", "failed"):
                    break
                time.sleep(0.05)
            assert state["status"] == "done", state
            assert state["result"]["reply"].startswith("解读:")
            assert state["result"]["elapsed"] >= 0.0

    def test_task_failure_surfaces_error(self, config_dir, monkeypatch):
        import time

        from fastapi.testclient import TestClient

        from easy_tdx.web.app import _create_app

        def fake_chat(self, prompt, system_prompt=None):
            async def _boom():
                raise LlmError("请求超时（180s 内无响应）")
            return _boom()

        monkeypatch.setattr(LlmClient, "chat", fake_chat)
        app = _create_app(enable_mac=False, enable_ui=False)
        with TestClient(app) as c:
            task_id = c.post("/api/v1/llm/chat/async", json={"prompt": "x"}).json()["task_id"]
            state = None
            for _ in range(50):
                state = c.get(f"/api/v1/llm/chat/tasks/{task_id}").json()
                if state["status"] in ("done", "failed"):
                    break
                time.sleep(0.05)
            assert state["status"] == "failed"
            assert "请求超时" in state["error"]

    def test_unknown_task_rejected(self, config_dir):
        """未知 task → 400（与 GET /backtest/tasks/{id} 的 ValueError 约定一致）。"""
        from fastapi.testclient import TestClient

        from easy_tdx.web.app import _create_app

        app = _create_app(enable_mac=False, enable_ui=False)
        with TestClient(app) as c:
            r = c.get("/api/v1/llm/chat/tasks/nonexistent")
            assert r.status_code == 400
            assert "未知任务" in r.json()["detail"]

    def test_async_success_records_history(self, config_dir, monkeypatch):
        """异步解读成功 → 自动落历史库（含策略上下文），供历史页查询。"""
        import time as _time

        from fastapi.testclient import TestClient

        from easy_tdx.web.app import _create_app

        async def fake_chat(self, prompt, system_prompt=None):
            return "解读正文"

        monkeypatch.setattr(LlmClient, "chat", fake_chat)
        app = _create_app(enable_mac=False, enable_ui=False)
        with TestClient(app) as c:
            ctx = {
                "strategy": "ma_cross",
                "strategy_label": "双均线交叉",
                "symbol": "600519",
                "category": "DAY",
                "params": {"fast": 5, "slow": 20},
                "start_date": "2024-01-01",
                "end_date": "2025-01-01",
            }
            tid = c.post("/api/v1/llm/chat/async",
                         json={"prompt": "报告", "context": ctx}).json()["task_id"]
            for _ in range(50):
                st = c.get(f"/api/v1/llm/chat/tasks/{tid}").json()
                if st["status"] in ("done", "failed"):
                    break
                _time.sleep(0.05)
            assert st["status"] == "done", st

            hist = c.get("/api/v1/llm/history").json()
            assert hist["count"] >= 1
            item = hist["items"][0]
            assert item["reply"] == "解读正文"
            assert item["strategy"] == "ma_cross" and item["symbol"] == "600519"
            assert item["params"] == {"fast": 5, "slow": 20}

            # 删除一条
            r = c.delete(f"/api/v1/llm/history/{item['id']}")
            assert r.json()["ok"] is True
            assert c.get("/api/v1/llm/history").json()["count"] == hist["count"] - 1

    def test_async_failure_not_recorded(self, config_dir, monkeypatch):
        """解读失败 → 不落历史（历史只归档成功解读）。"""
        import time as _time

        from fastapi.testclient import TestClient

        from easy_tdx.web.app import _create_app

        async def fake_chat(self, prompt, system_prompt=None):
            raise LlmError("boom")

        monkeypatch.setattr(LlmClient, "chat", fake_chat)
        app = _create_app(enable_mac=False, enable_ui=False)
        with TestClient(app) as c:
            tid = c.post("/api/v1/llm/chat/async", json={"prompt": "x"}).json()["task_id"]
            for _ in range(50):
                st = c.get(f"/api/v1/llm/chat/tasks/{tid}").json()
                if st["status"] in ("done", "failed"):
                    break
                _time.sleep(0.05)
            assert st["status"] == "failed"
            assert c.get("/api/v1/llm/history").json()["count"] == 0

    def test_submit_rejects_incomplete_config(self, config_dir):
        """custom 未填 url/model：提交期即 400（不等任务跑起来才失败）。"""
        from fastapi.testclient import TestClient

        from easy_tdx.web.app import _create_app

        app = _create_app(enable_mac=False, enable_ui=False)
        with TestClient(app) as c:
            r = c.post(
                "/api/v1/llm/chat/async",
                json={"prompt": "x", "override": {"provider": "custom"}},
            )
            assert r.status_code == 400
            assert "不完整" in r.json()["detail"]


class TestThinkingModelBlankContent:
    """思考型模型正文空白（reasoning_content 耗尽 max_tokens）的防御。

    v1.29.1 实测：GLM-5.x 思考链计入 max_tokens，预算耗尽时 content 为
    空白——truthy 但渲染为空（状态条报成功、正文空白）。解析层必须把
    这类响应转成可操作的错误，绝不返回空白字符串。
    """

    def _client(self, max_tokens: int = 4000) -> LlmClient:
        return LlmClient(LlmConfig(provider="zhipu", api_key="sk-x-1234567890",
                                   model="glm-5.3-flash", max_tokens=max_tokens))

    def test_normal_content_wins_over_reasoning(self):
        msg = {"content": "正文", "reasoning_content": "思考…", "role": "assistant"}
        assert self._client()._extract_reply_openai(msg, "stop") == "正文"

    def test_blank_content_with_reasoning_raises_actionable(self):
        msg = {"content": "   ", "reasoning_content": "思考" * 500, "role": "assistant"}
        with pytest.raises(LlmError, match="思考链.*4000.*16000"):
            self._client()._extract_reply_openai(msg, "length")

    def test_null_content_with_reasoning(self):
        msg = {"content": None, "reasoning_content": "思考", "role": "assistant"}
        with pytest.raises(LlmError, match="思考链"):
            self._client()._extract_reply_openai(msg, "length")

    def test_blank_content_without_reasoning(self):
        with pytest.raises(LlmError, match="content 为空"):
            self._client()._extract_reply_openai({"content": ""}, "stop")

    def test_length_finish_without_content(self):
        with pytest.raises(LlmError, match="截断"):
            self._client()._extract_reply_openai({"content": ""}, "length")

    def test_whitespace_reply_rejected_end_to_end(self, config_dir, monkeypatch):
        """端到端：伪 HTTP 返回空白正文 → chat() 抛错（任务态 failed 而非 done 空回复）。"""

        def fake_post(url, headers, payload, timeout):
            blank = chr(10) + "  " + chr(10)
            return {"choices": [{"message": {"content": blank, "reasoning_content": "r"},
                                 "finish_reason": "length"}]}

        monkeypatch.setattr(llm_mod, "_post_json", fake_post)
        with pytest.raises(LlmError, match="思考链"):
            asyncio.run(self._client().chat("报告"))

    def test_default_max_tokens_generous_for_thinking(self):
        assert LlmConfig().max_tokens >= 16000
