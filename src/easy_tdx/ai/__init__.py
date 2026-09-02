"""LLM 客户端与配置（多 Provider，WebUI 与配置文件双向兼容）。

借鉴社区 Fork（swimmingaaron/easy_tdx）的极简 LLM 客户端思路并扩展：
国产主流 Provider 预设（DeepSeek/通义千问/智谱/Kimi/MiniMax）+ OpenAI/
Claude/Ollama + 完全自定义，统一收敛到两种线上协议（openai 兼容 /
anthropic 原生）。

配置来源（字段级优先级，WebUI 与配置文件天然兼容）::

    ~/.easy_tdx/llm.json 字段值  >  环境变量  >  Provider 预设默认值

WebUI 保存 = 写这个 JSON 文件；手工编辑文件 = 下次请求即生效。环境变量
（``LLM_PROVIDER`` / ``LLM_API_KEY`` / ``LLM_BASE_URL`` / ``LLM_MODEL``）
与常见工具惯例一致，仅在文件缺字段时兜底。
"""

from easy_tdx.ai.llm import (
    PROVIDER_PRESETS,
    LlmClient,
    LlmConfig,
    load_config,
    mask_key,
    resolve_config,
    save_config,
)

__all__ = [
    "PROVIDER_PRESETS",
    "LlmClient",
    "LlmConfig",
    "load_config",
    "mask_key",
    "resolve_config",
    "save_config",
]
