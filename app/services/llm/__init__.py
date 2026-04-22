"""LLM provider infrastructure (И-08 Phase 4).

Domain services (like `import_moderator_service`) talk to an `LLMProvider`
abstraction, not to Anthropic directly. This keeps the moderator testable
without network calls and lets us swap the provider later (open-source
model via vLLM, or another vendor) without touching the business logic.

Entry point: `get_provider()` from `app.services.llm.registry`.
"""
from app.services.llm.base import LLMProvider, LLMResult, LLMUnavailableError
from app.services.llm.registry import get_provider

__all__ = ["LLMProvider", "LLMResult", "LLMUnavailableError", "get_provider"]
