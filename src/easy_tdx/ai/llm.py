"""多 Provider LLM 客户端：配置解析 + HTTP 调用。

零第三方依赖：HTTP 走标准库 urllib（经 ``asyncio.to_thread`` 异步化），
FastAPI 路由可直接 ``await``。

Provider 预设（``api_style``）：

===========  ========  ==============================================  ==================
provider     协议      base_url                                        默认模型
===========  ========  ==============================================  ==================
deepseek     openai    https://api.deepseek.com/v1                     deepseek-chat
qwen         openai    https://dashscope.aliyuncs.com/compatible-mode  qwen-plus
                       /v1
zhipu        openai    https://open.bigmodel.cn/api/paas/v4            glm-4-flash
kimi         openai    https://api.moonshot.cn/v1                      moonshot-v1-8k
minimax      openai    https://api.minimaxi.chat/v1                    MiniMax-Text-01
openai       openai    https://api.openai.com/v1                       gpt-4o-mini
claude       anthropic https://api.anthropic.com/v1                     claude-sonnet-4-5
ollama       openai    http://localhost:11434/v1                       qwen2.5:7b
custom       openai    （用户填写）                                     （用户填写）
===========  ========  ==============================================  ==================

预设的 base_url/默认模型只是初始填充值——WebUI 或 JSON 文件里均可覆盖
（自定义网关/代理场景直接改 url 即可）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

__all__ = [
    "PROVIDER_PRESETS",
    "LlmClient",
    "LlmConfig",
    "load_config",
    "mask_key",
    "resolve_config",
    "save_config",
]

logger = logging.getLogger(__name__)

#: 配置文件名（落在 EASY_TDX_CONFIG_DIR，与 watchlist/strategies 同目录）。
LLM_CONFIG_FILENAME = "llm.json"


@dataclass
class ProviderPreset:
    """单个 Provider 的展示信息与默认填充值。"""

    id: str
    label: str
    base_url: str
    default_model: str
    api_style: str = "openai"  # "openai" | "anthropic"
    needs_key: bool = True  # ollama 本地服务无需 key

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "api_style": self.api_style,
            "needs_key": self.needs_key,
        }


#: Provider 预设表（WebUI 下拉框数据源 + 未配置字段的兜底默认值）。
PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    p.id: p
    for p in (
        ProviderPreset("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
        ProviderPreset(
            "qwen",
            "通义千问 Qwen",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "qwen-plus",
        ),
        ProviderPreset("zhipu", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
        ProviderPreset("kimi", "Kimi (月之暗面)", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
        ProviderPreset("minimax", "MiniMax", "https://api.minimaxi.chat/v1", "MiniMax-Text-01"),
        ProviderPreset("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
        ProviderPreset(
            "claude",
            "Claude (Anthropic)",
            "https://api.anthropic.com/v1",
            "claude-sonnet-4-5",
            api_style="anthropic",
        ),
        ProviderPreset(
            "ollama",
            "Ollama（本地）",
            "http://localhost:11434/v1",
            "qwen2.5:7b",
            needs_key=False,
        ),
        ProviderPreset("custom", "自定义（OpenAI 兼容）", "", ""),
    )
}


@dataclass
class LlmConfig:
    """LLM 调用配置（WebUI 表单与 llm.json 的公共结构）。"""

    provider: str = "deepseek"
    api_url: str = ""  # 留空 = 用预设 base_url
    api_key: str = ""
    model: str = ""  # 留空 = 用预设默认模型
    temperature: float = 0.3
    # max_tokens 是"上限"而非目标（按实际生成计费）：思考型模型的思考链
    # 计入该预算，4000 会被整份报告的思考轻易耗尽导致正文空白，默认给足
    timeout: float = 180.0
    max_tokens: int = 16000
    system_prompt: str = field(
        default="你是一位严谨的 A 股量化投研分析师，基于给定的数据客观分析，"
        "不确定的内容明确说明，不构成投资建议。"
    )

    def to_dict(self, *, mask_api_key: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if mask_api_key:
            d["api_key"] = mask_key(self.api_key)
        return d


# ── 配置读写（文件 > 环境变量 > 预设） ────────────────────────────────────────


def config_path() -> Path:
    """配置文件路径（``$EASY_TDX_CONFIG_DIR/llm.json``，默认 ``~/.easy_tdx``）。"""
    base = Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))
    return base / LLM_CONFIG_FILENAME


def _read_config_file() -> dict[str, Any]:
    """直读 llm.json（无缓存——手工编辑即时生效）。损坏/不存在返回空 dict。"""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("读取 LLM 配置失败 %s: %s", p, exc)
        return {}


def load_config() -> LlmConfig:
    """加载配置：llm.json 显式字段 > 环境变量兜底（未填字段仍为空，调用时再取预设）。"""
    data = _read_config_file()
    env_url = os.environ.get("LLM_BASE_URL", "")
    cfg = LlmConfig(
        provider=str(data.get("provider") or os.environ.get("LLM_PROVIDER", "") or "deepseek"),
        api_url=str(data.get("api_url") or env_url or ""),
        api_key=str(data.get("api_key") or os.environ.get("LLM_API_KEY", "") or ""),
        model=str(data.get("model") or os.environ.get("LLM_MODEL", "") or ""),
        temperature=float(data.get("temperature", 0.3)),
        max_tokens=int(data.get("max_tokens", 16000)),
        timeout=float(data.get("timeout", 180.0)),
        system_prompt=str(data.get("system_prompt", "") or LlmConfig.system_prompt),
    )
    return cfg


def save_config(cfg: LlmConfig) -> Path:
    """写入 llm.json（WebUI 保存入口；目录惰性创建）。"""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return p


def resolve_config(cfg: LlmConfig | None = None) -> LlmConfig:
    """把配置的空字段用 Provider 预设补齐，得到可直接调用的完整配置。

    - ``api_url`` 空 → 预设 ``base_url``；
    - ``model`` 空 → 预设 ``default_model``；
    - provider 无预设（拼错）→ 按 custom 处理，url/model 必须已填。

    Raises:
        ValueError: 补齐后仍缺 api_url 或 model（custom 未填全）。
    """
    c = replace(cfg or load_config())
    preset = PROVIDER_PRESETS.get(c.provider, PROVIDER_PRESETS["custom"])
    if not c.api_url:
        c.api_url = preset.base_url
    if not c.model:
        c.model = preset.default_model
    if not c.api_url or not c.model:
        raise ValueError(
            f"LLM 配置不完整：provider={c.provider} 缺少 api_url 或 model，"
            "请在 AI 设置中补全"
        )
    return c


def mask_key(key: str) -> str:
    """API Key 脱敏展示：保头 3 尾 4，中间打码（短 key 全打码）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}***{key[-4:]}"


# ── HTTP 客户端（标准库实现） ─────────────────────────────────────────────────


class LlmError(RuntimeError):
    """LLM 调用失败（网络/鉴权/响应格式）。"""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _post_json(
    url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
) -> dict[str, Any]:
    """同步 POST JSON（在线程池里跑），返回解析后的 JSON。

    urllib 默认带 ``User-Agent: Python-urllib``，部分网关拒绝——显式带 UA。
    超时单独成类报错：非流式 chat 接口要等模型**整段回复生成完**才回包，
    大 Prompt（如整份回测报告解读）生成 1-3 分钟很正常，读超时≠网络故障，
    报错必须把「调大超时」这个动作说清楚（v1.29.1 实测踩坑）。
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": "easy-tdx/llm", "Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise LlmError(f"LLM API HTTP {exc.code}: {body}", status=exc.code) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise LlmError(_timeout_message(timeout)) from exc
        raise LlmError(f"LLM API 网络错误: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LlmError(_timeout_message(timeout)) from exc
    except json.JSONDecodeError as exc:
        raise LlmError(f"LLM API 响应不是合法 JSON: {exc}") from exc


def _timeout_message(timeout: float) -> str:
    return (
        f"请求超时（{timeout:.0f}s 内无响应）——非流式接口需等模型生成完整段回复，"
        "大报告解读 1-3 分钟属正常。可在「AI 设置」调大「超时（秒）」，"
        "或换生成更快的模型后重试"
    )


class LlmClient:
    """单次配置快照的 LLM 调用客户端（无连接状态，可随时重建）。"""

    def __init__(self, cfg: LlmConfig | None = None) -> None:
        self._cfg = resolve_config(cfg)

    @property
    def config(self) -> LlmConfig:
        return self._cfg

    async def chat(self, prompt: str, system_prompt: str | None = None) -> str:
        """发一轮对话，返回模型回复文本。

        Args:
            prompt: 用户消息（如回测报告组装成的解读 Prompt）。
            system_prompt: 系统提示，None = 用配置里的默认。

        Raises:
            LlmError: 网络/鉴权/格式错误（含未配置 api_key 的场景）。
        """
        cfg = self._cfg
        preset = PROVIDER_PRESETS.get(cfg.provider, PROVIDER_PRESETS["custom"])
        if preset.needs_key and not cfg.api_key:
            raise LlmError(
                f"未配置 {preset.label} 的 API Key——请在 WebUI「AI 设置」页"
                "或 ~/.easy_tdx/llm.json 中填写（或设置 LLM_API_KEY 环境变量）"
            )
        system = system_prompt if system_prompt is not None else cfg.system_prompt
        return await asyncio.to_thread(self._chat_sync, prompt, system, preset.api_style)

    # -- 同步实现（to_thread 里跑） --------------------------------------------

    def _chat_sync(self, prompt: str, system: str, api_style: str) -> str:
        if api_style == "anthropic":
            return self._chat_anthropic(prompt, system)
        return self._chat_openai(prompt, system)

    def _chat_openai(self, prompt: str, system: str) -> str:
        cfg = self._cfg
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_tokens,
        }
        url = f"{cfg.api_url.rstrip('/')}/chat/completions"
        data = _post_json(url, headers, payload, cfg.timeout)
        try:
            message = data["choices"][0]["message"]
            finish = str(data["choices"][0].get("finish_reason") or "")
            return self._extract_reply_openai(message, finish)
        except LlmError:
            raise
        except (KeyError, IndexError, TypeError) as exc:
            raw = json.dumps(data, ensure_ascii=False)[:300]
            raise LlmError(f"LLM 响应格式异常: {raw}") from exc

    def _extract_reply_openai(self, message: dict[str, Any], finish: str) -> str:
        """从 OpenAI 兼容响应的 message 里提取正文，处理思考型模型的空白正文。

        思考型模型（GLM-5.x / DeepSeek-R1 / o 系列等）的 ``reasoning_content``
        计入 max_tokens：预算被思考链耗尽时 ``content`` 为空白——truthy 但
        渲染为空（v1.29.1 实测：状态条报成功、正文空白）。这里显式拦截：
        空白正文一律报可操作的错误（提示调大 max_tokens），绝不返回空串。
        """
        content = message.get("content")
        text = str(content) if content is not None else ""
        if text.strip():
            return text
        reasoning = message.get("reasoning_content") or message.get("reasoning")
        if reasoning:
            raise LlmError(
                f"模型只返回了思考链（reasoning_content {len(str(reasoning))} 字），"
                f"未生成正文——max_tokens={self._cfg.max_tokens} 大概率被思考耗尽"
                f"（finish_reason={finish or 'unknown'}）。"
                "请在「AI 设置」把 Max Tokens 调大（思考型模型建议 ≥16000）后重试"
            )
        if finish == "length":
            raise LlmError(
                "模型输出被 max_tokens 截断且无正文，请在「AI 设置」调大 Max Tokens 后重试"
            )
        raw = json.dumps(message, ensure_ascii=False)[:300]
        raise LlmError(f"LLM 响应 message.content 为空: {raw}")

    def _chat_anthropic(self, prompt: str, system: str) -> str:
        cfg = self._cfg
        headers = {
            "x-api-key": cfg.api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        url = f"{cfg.api_url.rstrip('/')}/messages"
        data = _post_json(url, headers, payload, cfg.timeout)
        try:
            blocks = data["content"]
            return "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raw = json.dumps(data, ensure_ascii=False)[:300]
            raise LlmError(f"LLM 响应格式异常: {raw}") from exc

    async def test(self) -> dict[str, Any]:
        """连通性测试：发一句极短 ping，返回 ok/延迟/样例回复。"""
        t0 = time.perf_counter()
        try:
            reply = await self.chat(
                "请只回复两个字：OK", system_prompt="You are a connectivity probe."
            )
            return {
                "ok": True,
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "model": self._cfg.model,
                "provider": self._cfg.provider,
                "reply": reply.strip()[:100],
            }
        except LlmError as exc:
            return {
                "ok": False,
                "latency_ms": round((time.perf_counter() - t0) * 1000),
                "model": self._cfg.model,
                "provider": self._cfg.provider,
                "error": str(exc),
            }
