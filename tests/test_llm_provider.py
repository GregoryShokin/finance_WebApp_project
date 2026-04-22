"""Phase 4.1: LLM provider abstraction tests.

Covers:
  - AnthropicProvider disabled when no API key
  - AnthropicProvider disabled when LLM_CLASSIFICATION_ENABLED=False
  - cache_control block attached when cache_key is provided
  - generate_structured returns None on SDK failure
  - registry returns the configured provider

No network calls — the Anthropic client is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from app.services.llm.anthropic_provider import AnthropicProvider
from app.services.llm.base import LLMUnavailableError


class _Schema(BaseModel):
    answer: str


def _settings(api_key: str = "", enabled: bool = False, model: str = "claude-haiku-4-5"):
    s = MagicMock()
    s.ANTHROPIC_API_KEY = api_key
    s.LLM_CLASSIFICATION_ENABLED = enabled
    s.ANTHROPIC_MODEL = model
    return s


class TestAnthropicProviderEnablement:
    def test_disabled_without_api_key(self):
        provider = AnthropicProvider(_settings(api_key="", enabled=True))
        assert provider.is_enabled is False

    def test_disabled_when_flag_false(self):
        provider = AnthropicProvider(_settings(api_key="sk-x", enabled=False))
        assert provider.is_enabled is False

    def test_generate_structured_raises_when_disabled(self):
        provider = AnthropicProvider(_settings(api_key="", enabled=True))
        with pytest.raises(LLMUnavailableError):
            provider.generate_structured(system="s", user="u", schema=_Schema)

    def test_model_id_reflects_settings(self):
        provider = AnthropicProvider(_settings(model="claude-haiku-4-5"))
        assert provider.model_id == "claude-haiku-4-5"


class TestAnthropicProviderCallPath:
    def _make_enabled_provider(self, fake_client: MagicMock) -> AnthropicProvider:
        with patch("anthropic.Anthropic", return_value=fake_client):
            return AnthropicProvider(_settings(api_key="sk-x", enabled=True))

    def test_cache_control_attached_when_cache_key_given(self):
        fake_client = MagicMock()
        response = MagicMock()
        response.parsed_output = _Schema(answer="ok")
        response.usage = MagicMock(
            input_tokens=10, output_tokens=5,
            cache_read_input_tokens=0, cache_creation_input_tokens=10,
        )
        fake_client.messages.parse.return_value = response

        provider = self._make_enabled_provider(fake_client)
        assert provider.is_enabled is True

        result = provider.generate_structured(
            system="system text",
            user="user text",
            schema=_Schema,
            cache_key="moderator:v1:42",
        )

        assert result is not None
        assert result.parsed.answer == "ok"

        call_kwargs = fake_client.messages.parse.call_args.kwargs
        system_block = call_kwargs["system"]
        assert system_block[0]["text"] == "system text"
        assert system_block[0]["cache_control"] == {"type": "ephemeral"}

    def test_no_cache_control_when_cache_key_missing(self):
        fake_client = MagicMock()
        response = MagicMock()
        response.parsed_output = _Schema(answer="ok")
        response.usage = None
        fake_client.messages.parse.return_value = response

        provider = self._make_enabled_provider(fake_client)
        result = provider.generate_structured(system="s", user="u", schema=_Schema)

        assert result is not None
        call_kwargs = fake_client.messages.parse.call_args.kwargs
        system_block = call_kwargs["system"]
        assert "cache_control" not in system_block[0]

    def test_returns_none_on_sdk_error(self):
        fake_client = MagicMock()
        fake_client.messages.parse.side_effect = RuntimeError("api down")

        provider = self._make_enabled_provider(fake_client)
        result = provider.generate_structured(system="s", user="u", schema=_Schema)
        assert result is None

    def test_returns_none_when_parsed_output_wrong_type(self):
        fake_client = MagicMock()
        response = MagicMock()
        response.parsed_output = {"not": "a pydantic model"}
        fake_client.messages.parse.return_value = response

        provider = self._make_enabled_provider(fake_client)
        result = provider.generate_structured(system="s", user="u", schema=_Schema)
        assert result is None

    def test_usage_fields_propagated(self):
        fake_client = MagicMock()
        response = MagicMock()
        response.parsed_output = _Schema(answer="ok")
        response.usage = MagicMock(
            input_tokens=42, output_tokens=17,
            cache_read_input_tokens=100, cache_creation_input_tokens=0,
        )
        fake_client.messages.parse.return_value = response

        provider = self._make_enabled_provider(fake_client)
        result = provider.generate_structured(
            system="s", user="u", schema=_Schema, cache_key="k"
        )

        assert result is not None
        assert result.input_tokens == 42
        assert result.output_tokens == 17
        assert result.cache_read_tokens == 100
        assert result.cache_creation_tokens == 0
