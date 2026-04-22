"""Provider registry (И-08 Phase 4.1).

Single entry point for domain services to get an `LLMProvider`. Today only
Anthropic is wired; future providers (open-source via vLLM, another vendor)
plug in here without touching callers.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, settings
from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import LLMProvider


@lru_cache(maxsize=1)
def get_provider(app_settings: Settings | None = None) -> LLMProvider:
    """Return the configured LLM provider. Cached per-process.

    Pass a non-None `app_settings` in tests to avoid the cache; in production
    callers use the module-level singleton.
    """
    config = app_settings or settings
    # Only one vendor for now; when more land we'll branch on config.LLM_PROVIDER.
    return AnthropicProvider(config)
