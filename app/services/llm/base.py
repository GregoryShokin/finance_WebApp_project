"""Abstract LLM provider + result types (И-08 Phase 4.1).

Any provider implementation must supply `generate_structured(system, user,
schema, *, max_tokens, cache_key)`. The return value is either a parsed
instance of `schema` (subclass of `pydantic.BaseModel`) or `None` if the
model's output could not be coerced to the schema.

Callers that need cost/latency telemetry can inspect `LLMResult.usage` when
the provider populates it. Everything outside of `generate_structured` —
rate limiting, retry policy, anonymization — belongs to higher layers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel


class LLMUnavailableError(RuntimeError):
    """Raised when the provider is disabled or the client cannot be created.

    The moderator service catches this and falls back to a `skipped` hypothesis
    state — the wizard still opens, there are simply no LLM suggestions.
    """


@dataclass(frozen=True)
class LLMResult:
    """Return value of `generate_structured` when the call succeeded.

    Holds the parsed object plus optional usage stats for the metrics pipeline
    in Phase 6 (token cost per session).
    """

    parsed: Any  # concrete type is the schema class the caller passed in
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None


T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Abstract provider. Implementations live in `app/services/llm/<vendor>_provider.py`."""

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """True if the provider is configured and ready to accept calls."""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Identifier of the underlying model — useful for telemetry."""

    @abstractmethod
    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 1024,
        cache_key: str | None = None,
    ) -> LLMResult | None:
        """Ask the model for a response that conforms to `schema`.

        Returns `None` when the model returned text that could not be parsed
        into the schema. Returns an `LLMResult` with `parsed` set to an
        instance of `schema` on success.

        `cache_key` is an opaque hint to the provider that the `system` prompt
        is stable across calls; providers that support prompt caching
        (Anthropic `cache_control: ephemeral`) should use it.
        """
