"""Anthropic (Claude) implementation of LLMProvider (И-08 Phase 4.1).

Uses the `anthropic` SDK's structured-output path. System prompt is wrapped
in a `cache_control: ephemeral` block when `cache_key` is provided — the
SDK takes care of the cache-hit bookkeeping.

Errors are swallowed and logged; a failed call returns `None`. The
moderator service interprets `None` as "no hypothesis from LLM" and the
wizard degrades to manual review.
"""
from __future__ import annotations

import logging
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.config import Settings
from app.services.llm.base import LLMProvider, LLMResult, LLMUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model = settings.ANTHROPIC_MODEL
        self._enabled = bool(
            settings.LLM_CLASSIFICATION_ENABLED and settings.ANTHROPIC_API_KEY
        )
        self._client: Any | None = None

        if self._enabled:
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            except Exception as exc:
                logger.warning("Failed to init Anthropic client: %s", exc)
                self._enabled = False
                self._client = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    @property
    def model_id(self) -> str:
        return self._model

    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 1024,
        cache_key: str | None = None,
    ) -> LLMResult | None:
        if not self.is_enabled:
            raise LLMUnavailableError("Anthropic provider is not configured")

        system_block: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cache_key is not None:
            system_block[0]["cache_control"] = {"type": "ephemeral"}

        try:
            response = self._client.messages.parse(  # type: ignore[union-attr]
                model=self._model,
                max_tokens=max_tokens,
                system=system_block,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
            )
        except Exception as exc:
            logger.warning("Anthropic structured call failed: %s", exc)
            return None

        parsed = getattr(response, "parsed_output", None)
        if parsed is None or not isinstance(parsed, schema):
            return None

        usage = getattr(response, "usage", None)
        return LLMResult(
            parsed=parsed,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", None) if usage else None,
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", None) if usage else None,
        )
