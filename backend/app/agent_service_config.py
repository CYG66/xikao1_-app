"""Static model-provider configuration for the agent service.

This module deliberately contains no service state or network calls. Keeping
provider registration here prevents the orchestration service from becoming
the owner of deployment configuration as well as conversation behavior.
"""

from __future__ import annotations


PROVIDERS = {
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "anthropic": ("Claude", "https://api.anthropic.com/v1"),
    "gemini": ("Gemini", "https://generativelanguage.googleapis.com/v1beta"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com"),
    "qwen": ("通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "kimi": ("Kimi", "https://api.moonshot.cn/v1"),
    "glm": ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4"),
    "minimax": ("MiniMax", "https://api.minimaxi.com/v1"),
}

PROVIDER_API_KEY_ENV = {
    provider: f"{provider.upper()}_API_KEY" for provider in PROVIDERS
}
PROVIDER_MODEL_ENV = {
    provider: f"{provider.upper()}_MODEL" for provider in PROVIDERS
}
DEFAULT_MODELS = {
    "openai": "gpt-5.1",
    "anthropic": "claude-opus-5",
    "gemini": "gemini-3.6-flash",
    "deepseek": "deepseek-chat",
    "qwen": "qwen3.7-max",
    "kimi": "kimi-k2.5",
    "glm": "glm-5",
    "minimax": "MiniMax-M2.7",
}

DEEPSEEK_BASE_MODEL_ENV = "DEEPSEEK_BASE_MODEL"
DEEPSEEK_ADVANCED_MODEL_ENV = "DEEPSEEK_ADVANCED_MODEL"
