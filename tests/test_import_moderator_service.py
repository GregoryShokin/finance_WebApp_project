"""Phase 4.2 / 4.7 / 4.8: moderator service tests.

Covers:
  - moderate_cluster returns None when provider disabled (fallback path)
  - moderate_cluster returns None when provider returns None
  - predicted_category_id is nulled when it doesn't belong to user
  - prompts contain ONLY skeletons/placeholders — no raw phone/contract/iban/...
    (anonymization invariant, Phase 4.7)
  - cache_key is passed through to the provider (prompt caching, Phase 4.8)
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.import_cluster_service import Cluster
from app.services.import_moderator_service import (
    ClusterHypothesis,
    ImportModeratorService,
    ModerationContext,
)
from app.services.llm.base import LLMResult, LLMUnavailableError


def _cluster(
    skeleton: str = "магазин <AMOUNT>",
    identifier_key: str | None = None,
    bank_code: str | None = "tinkoff",
    direction: str = "expense",
    count: int = 2,
) -> Cluster:
    return Cluster(
        fingerprint="fp-a",
        row_ids=(1, 2),
        count=count,
        total_amount=Decimal("200.00"),
        direction=direction,
        skeleton=skeleton,
        identifier_key=identifier_key,
        identifier_value="SHOULD_NEVER_LEAK_TO_LLM",  # raw value, not part of prompt
        bank_code=bank_code,
        example_row_ids=(1, 2),
        candidate_rule_id=None,
        candidate_category_id=None,
        rule_source="none",
        confidence=0.0,
    )


def _category(id: int = 1, name: str = "Еда", kind: str = "expense"):
    return SimpleNamespace(id=id, name=name, kind=kind)


def _context(user_id: int = 7, categories=None, rule_snippets=None):
    return ModerationContext(
        user_id=user_id,
        categories=categories if categories is not None else [_category(10, "Еда")],
        active_rule_snippets=rule_snippets or [],
    )


class TestFallback:
    def test_returns_none_when_provider_disabled(self):
        provider = MagicMock()
        provider.is_enabled = False
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        result = svc.moderate_cluster(_cluster(), _context())
        assert result is None
        provider.generate_structured.assert_not_called()

    def test_returns_none_when_provider_returns_none(self):
        provider = MagicMock()
        provider.is_enabled = True
        provider.generate_structured.return_value = None
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        result = svc.moderate_cluster(_cluster(), _context())
        assert result is None

    def test_returns_none_when_provider_raises_unavailable(self):
        provider = MagicMock()
        provider.is_enabled = True
        provider.generate_structured.side_effect = LLMUnavailableError("down")
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        result = svc.moderate_cluster(_cluster(), _context())
        assert result is None


class TestCategoryValidation:
    def test_returned_category_nulled_if_not_in_user_categories(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular",
            direction="expense",
            predicted_category_id=9999,  # unknown ID
            confidence=0.85,
            reasoning="test",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        result = svc.moderate_cluster(_cluster(), _context(categories=[_category(10, "Еда")]))
        assert result is not None
        assert result.predicted_category_id is None
        assert result.confidence == 0.85

    def test_valid_category_preserved(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular",
            direction="expense",
            predicted_category_id=10,
            confidence=0.9,
            reasoning="valid",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        result = svc.moderate_cluster(_cluster(), _context(categories=[_category(10, "Еда")]))
        assert result.predicted_category_id == 10


class TestCreditPaymentGuard:
    """§12.3: operation_type='credit_payment' is forbidden end-to-end.

    Even if the model ignores the prompt and returns it, the moderator
    must coerce the hypothesis into a safe shape before returning.
    """

    def test_credit_payment_coerced_to_transfer(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="credit_payment",
            direction="expense",
            predicted_category_id=10,
            confidence=0.9,
            reasoning="LLM попробовал credit_payment",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        result = svc.moderate_cluster(_cluster(), _context(categories=[_category(10, "Еда")]))
        assert result is not None
        assert result.operation_type == "transfer"
        assert result.predicted_category_id is None
        # confidence and reasoning from the model survive the coercion
        assert result.confidence == 0.9

    def test_system_prompt_bans_credit_payment(self):
        """The prompt shown to the model must NOT list credit_payment as a choice."""
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="transfer", direction="expense",
            predicted_category_id=None, confidence=0.5, reasoning="x",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        svc.moderate_cluster(_cluster(), _context())
        call_kwargs = provider.generate_structured.call_args.kwargs
        system_text = call_kwargs["system"]
        # Find the line that enumerates allowed operation_type values.
        allowed_line = next(
            line for line in system_text.splitlines()
            if line.lstrip().startswith("1. operation_type")
        )
        # It must NOT include credit_payment in the allowed list.
        assert "credit_payment" not in allowed_line
        # But the prompt MUST explicitly forbid credit_payment somewhere —
        # the model should be told, not just left to guess.
        assert "credit_payment" in system_text
        assert "запрещён" in system_text


class TestAnonymization:
    """Phase 4.7: raw identifiers must never appear in the LLM payload."""

    def test_raw_identifier_value_not_in_prompts(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular", direction="expense",
            predicted_category_id=None, confidence=0.5, reasoning="test",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        cluster = _cluster(
            skeleton="перевод <CONTRACT> на <PERSON>",
            identifier_key="contract",
        )
        # identifier_value is "SHOULD_NEVER_LEAK_TO_LLM" — hardcoded in _cluster
        svc.moderate_cluster(cluster, _context())

        call_kwargs = provider.generate_structured.call_args.kwargs
        system_text = call_kwargs["system"]
        user_text = call_kwargs["user"]
        combined = system_text + "\n" + user_text

        assert "SHOULD_NEVER_LEAK_TO_LLM" not in combined

    def test_identifier_key_may_appear_but_not_value(self):
        """We tell the LLM 'a contract is present' — the key — but not WHICH contract."""
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular", direction="expense",
            predicted_category_id=None, confidence=0.5, reasoning="x",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        svc.moderate_cluster(_cluster(identifier_key="phone"), _context())
        call_kwargs = provider.generate_structured.call_args.kwargs
        assert "phone" in call_kwargs["user"]

    def test_active_rule_snippets_included_in_system_prompt(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular", direction="expense",
            predicted_category_id=None, confidence=0.5, reasoning="x",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        ctx = _context(rule_snippets=["магазин продукты → Еда", "такси → Транспорт"])
        svc.moderate_cluster(_cluster(), ctx)

        call_kwargs = provider.generate_structured.call_args.kwargs
        system_text = call_kwargs["system"]
        assert "магазин продукты → Еда" in system_text
        assert "такси → Транспорт" in system_text


class TestPromptCaching:
    """Phase 4.8: cache_key propagated to provider so Anthropic can reuse cache."""

    def test_cache_key_uses_user_id(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular", direction="expense",
            predicted_category_id=None, confidence=0.5, reasoning="x",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        svc.moderate_cluster(_cluster(), _context(user_id=42))
        call_kwargs = provider.generate_structured.call_args.kwargs
        assert call_kwargs["cache_key"] == "moderator:v1:42"

    def test_schema_matches_hypothesis_model(self):
        provider = MagicMock()
        provider.is_enabled = True
        hypothesis = ClusterHypothesis(
            operation_type="regular", direction="expense",
            predicted_category_id=None, confidence=0.5, reasoning="x",
        )
        provider.generate_structured.return_value = LLMResult(parsed=hypothesis)
        svc = ImportModeratorService(db=MagicMock(), provider=provider)

        svc.moderate_cluster(_cluster(), _context())
        call_kwargs = provider.generate_structured.call_args.kwargs
        assert call_kwargs["schema"] is ClusterHypothesis
