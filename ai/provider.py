"""Public AI provider facade and production pool construction."""
from __future__ import annotations

from rehan_bot.ai.errors import ProviderError, ProviderErrorKind, classify_status
from rehan_bot.ai.fallback import VisionFallbackChain, VisionProvider
from rehan_bot.ai.key_pool import KeyState, RoundRobinKeyPool
from rehan_bot.ai.providers import DeepSeekVisionProvider, GeminiVisionProvider, GroqVisionProvider, OpenAIVisionProvider, OpenRouterVisionProvider
from rehan_bot.config import Settings

__all__ = [
    "ProviderError",
    "ProviderErrorKind",
    "classify_status",
    "KeyState",
    "RoundRobinKeyPool",
    "VisionProvider",
    "VisionFallbackChain",
    "OpenAIVisionProvider",
    "GeminiVisionProvider",
    "OpenRouterVisionProvider",
    "GroqVisionProvider",
    "DeepSeekVisionProvider",
    "build_vision_fallback_chain",
]


def build_vision_fallback_chain(settings: Settings | None = None) -> VisionFallbackChain:
    """Build the configured multimodal chain from typed settings."""
    cfg = settings or Settings()
    entries = []
    if cfg.gemini_api_key_pool:
        entries.append(("gemini", GeminiVisionProvider(RoundRobinKeyPool(cfg.gemini_api_key_pool), cfg.gemini_model, cfg.ai_timeout_seconds)))
    if cfg.openai_api_key_pool:
        entries.append(("openai", OpenAIVisionProvider(RoundRobinKeyPool(cfg.openai_api_key_pool), cfg.openai_model, cfg.ai_timeout_seconds)))
    if cfg.openrouter_api_key_pool:
        entries.append(("openrouter", OpenRouterVisionProvider(RoundRobinKeyPool(cfg.openrouter_api_key_pool), cfg.openrouter_model, cfg.ai_timeout_seconds)))
    if cfg.groq_api_key_pool:
        entries.append(("groq", GroqVisionProvider(RoundRobinKeyPool(cfg.groq_api_key_pool), cfg.groq_model, cfg.ai_timeout_seconds)))
    if cfg.deepseek_api_key_pool:
        entries.append(("deepseek", DeepSeekVisionProvider(RoundRobinKeyPool(cfg.deepseek_api_key_pool), cfg.deepseek_model, cfg.ai_timeout_seconds)))
    from rehan_bot.ai.fallback import ProviderEntry
    if not entries:
        raise RuntimeError("No multimodal AI API keys are configured")
    return VisionFallbackChain(tuple(ProviderEntry(name, provider) for name, provider in entries))
