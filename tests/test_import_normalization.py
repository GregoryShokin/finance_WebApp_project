"""Unit tests for app.services.import_normalization.

Tests for normalize(), enrich() (minimal), and apply_decisions() in isolation.
Regression guard: running existing import test suites confirms full pipeline works.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.schemas.normalized_row import DecisionRow, DerivedRow, EnrichmentSuggestion, ParsedRow
from app.services.import_normalization import (
    _CREDIT_PAYMENT_KEYWORDS,
    _RAW_TYPES_REQUIRING_CREDIT_SPLIT,
    apply_decisions,
    normalize,
)
from app.services.import_normalizer_v2 import ExtractedTokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parsed(
    *,
    description: str = "Перевод по номеру телефона +79161234567",
    direction: str = "expense",
    amount: str = "1000.00",
    raw_type: str | None = None,
    counterparty_raw: str | None = None,
) -> ParsedRow:
    return ParsedRow(
        date=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        amount=Decimal(amount),
        currency="RUB",
        direction=direction,
        description=description,
        raw_type=raw_type,
        balance_after=None,
        source_reference=None,
        account_hint=None,
        counterparty_raw=counterparty_raw,
    )


def _make_derived(
    *,
    skeleton: str = "перевод <phone>",
    fingerprint: str = "abc123",
    is_transfer_like: bool = False,
    is_refund_like: bool = False,
    requires_credit_split_hint: bool = False,
    refund_brand: str | None = None,
) -> DerivedRow:
    return DerivedRow(
        skeleton=skeleton,
        fingerprint=fingerprint,
        tokens=ExtractedTokens(),
        transfer_identifier=None,
        is_transfer_like=is_transfer_like,
        is_refund_like=is_refund_like,
        refund_brand=refund_brand,
        requires_credit_split_hint=requires_credit_split_hint,
        normalizer_version=2,
    )


def _make_suggestion(
    *,
    suggested_account_id: int | None = 1,
    suggested_target_account_id: int | None = None,
    suggested_category_id: int | None = 5,
    suggested_operation_type: str = "regular",
    suggested_type: str = "expense",
    normalized_description: str | None = "кофе",
) -> EnrichmentSuggestion:
    return EnrichmentSuggestion(
        suggested_account_id=suggested_account_id,
        suggested_target_account_id=suggested_target_account_id,
        suggested_category_id=suggested_category_id,
        suggested_operation_type=suggested_operation_type,
        suggested_type=suggested_type,
        normalized_description=normalized_description,
        assignment_confidence=0.8,
        assignment_reasons=[],
        review_reasons=[],
        needs_manual_review=False,
    )


# ---------------------------------------------------------------------------
# normalize() tests
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_returns_parsed_and_derived(self):
        raw_row = {
            "Дата операции": "15.01.2026",
            "Описание": "Кофе Чашка",
            "Сумма": "-150.00",
        }
        field_mapping = {
            "date": "Дата операции",
            "description": "Описание",
            "amount": "Сумма",
        }
        parsed, derived = normalize(
            raw_row=raw_row,
            field_mapping=field_mapping,
            date_format="%d.%m.%Y",
            default_currency="RUB",
            bank="tbank",
            account_id=1,
        )
        assert isinstance(parsed, ParsedRow)
        assert isinstance(derived, DerivedRow)
        assert parsed.description == "Кофе Чашка"
        assert parsed.amount == Decimal("150.00")
        assert parsed.direction == "expense"
        assert parsed.currency == "RUB"

    def test_derived_fingerprint_uses_original_description(self):
        raw_row = {
            "Дата операции": "15.01.2026",
            "Описание": "Перевод Иванов Иван",
            "Сумма": "-500.00",
        }
        field_mapping = {
            "date": "Дата операции",
            "description": "Описание",
            "amount": "Сумма",
        }
        parsed, derived = normalize(
            raw_row=raw_row,
            field_mapping=field_mapping,
            date_format="%d.%m.%Y",
            default_currency="RUB",
            bank="tbank",
            account_id=1,
        )
        assert len(derived.fingerprint) == 16
        assert derived.skeleton != ""

    def test_transfer_keyword_sets_is_transfer_like(self):
        raw_row = {
            "Дата": "15.01.2026",
            "Описание": "Внешний перевод по номеру телефона +79161234567",
            "Сумма": "-5000.00",
        }
        field_mapping = {"date": "Дата", "description": "Описание", "amount": "Сумма"}
        _, derived = normalize(
            raw_row=raw_row,
            field_mapping=field_mapping,
            date_format="%d.%m.%Y",
            default_currency="RUB",
            bank="tbank",
            account_id=1,
        )
        assert derived.is_transfer_like is True

    def test_refund_keyword_sets_is_refund_like(self):
        raw_row = {
            "Дата": "15.01.2026",
            "Описание": "Возврат оплаты KOFEMOLOKO Volgodonsk",
            "Сумма": "500.00",
        }
        field_mapping = {"date": "Дата", "description": "Описание", "amount": "Сумма"}
        _, derived = normalize(
            raw_row=raw_row,
            field_mapping=field_mapping,
            date_format="%d.%m.%Y",
            default_currency="RUB",
            bank="tbank",
            account_id=1,
        )
        assert derived.is_refund_like is True

    def test_credit_payment_raw_type_sets_hint(self):
        raw_row = {
            "Дата": "15.01.2026",
            "Описание": "Погашение кредита",
            "Сумма": "-12000.00",
            "Тип": "credit_payment",
        }
        field_mapping = {
            "date": "Дата",
            "description": "Описание",
            "amount": "Сумма",
            "raw_type": "Тип",
        }
        _, derived = normalize(
            raw_row=raw_row,
            field_mapping=field_mapping,
            date_format="%d.%m.%Y",
            default_currency="RUB",
            bank="tbank",
            account_id=1,
        )
        assert derived.requires_credit_split_hint is True


# ---------------------------------------------------------------------------
# apply_decisions() tests — operation_type priority ladder
# ---------------------------------------------------------------------------

class TestApplyDecisions:
    SESSION_ACCOUNT = 10

    def _decide(self, parsed, derived, suggestion, rule=None):
        return apply_decisions(
            parsed=parsed,
            derived=derived,
            suggestion=suggestion,
            category_rule=rule,
            session_account_id=self.SESSION_ACCOUNT,
        )

    # (2) credit_split_hint → transfer
    def test_credit_split_hint_overrides_everything(self):
        parsed = _make_parsed(raw_type="credit_payment")
        derived = _make_derived(requires_credit_split_hint=True)
        suggestion = _make_suggestion(suggested_operation_type="regular")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "transfer"
        assert decision.requires_credit_split is True

    # (3) raw_type mapping
    def test_raw_type_purchase_maps_to_regular(self):
        parsed = _make_parsed(raw_type="purchase")
        derived = _make_derived()
        suggestion = _make_suggestion(suggested_operation_type="transfer")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "regular"

    def test_raw_type_investment_buy(self):
        parsed = _make_parsed(raw_type="investment_buy", direction="expense")
        derived = _make_derived()
        suggestion = _make_suggestion(suggested_operation_type="regular")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "investment_buy"

    # (4) is_refund_like
    def test_refund_signal_wins_over_enrichment(self):
        parsed = _make_parsed(description="Возврат оплаты КОFE Msk")
        derived = _make_derived(is_refund_like=True)
        suggestion = _make_suggestion(suggested_operation_type="regular")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "refund"

    # (5) is_transfer_like
    def test_transfer_signal_wins_over_enrichment(self):
        parsed = _make_parsed(description="Перевод между счетами")
        derived = _make_derived(is_transfer_like=True)
        suggestion = _make_suggestion(suggested_operation_type="regular")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "transfer"

    # (6) enrichment (weakest)
    def test_enrichment_suggestion_used_when_no_signals(self):
        parsed = _make_parsed(raw_type=None)
        derived = _make_derived(is_transfer_like=False, is_refund_like=False)
        suggestion = _make_suggestion(suggested_operation_type="investment_buy")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "investment_buy"

    # (7) keyword credit-split detection when op=transfer
    def test_credit_keyword_in_description_triggers_split_for_transfer(self):
        parsed = _make_parsed(
            description="Платёж по кредиту Тинькофф",
            raw_type="transfer",
        )
        derived = _make_derived(
            skeleton="платёж по кредиту тинькофф",
            is_transfer_like=True,
        )
        suggestion = _make_suggestion(suggested_operation_type="transfer")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.operation_type == "transfer"
        assert decision.requires_credit_split is True

    # Category clearing for transfers
    def test_category_cleared_for_transfer(self):
        parsed = _make_parsed()
        derived = _make_derived(is_transfer_like=True)
        suggestion = _make_suggestion(
            suggested_operation_type="transfer",
            suggested_category_id=99,
        )
        decision = self._decide(parsed, derived, suggestion)
        assert decision.category_id is None

    # Rule takes precedence for category
    def test_rule_category_overrides_enrichment(self):
        rule = MagicMock()
        rule.id = 42
        rule.category_id = 7
        parsed = _make_parsed(raw_type=None)
        derived = _make_derived()
        suggestion = _make_suggestion(suggested_category_id=5)
        decision = self._decide(parsed, derived, suggestion, rule=rule)
        assert decision.category_id == 7
        assert decision.applied_rule_id == 42
        assert decision.decision_source == "rule"

    # Transfer account routing — income
    def test_income_transfer_routes_source_to_target(self):
        parsed = _make_parsed(direction="income")
        derived = _make_derived(is_transfer_like=True)
        suggestion = _make_suggestion(
            suggested_operation_type="transfer",
            suggested_type="income",
            suggested_account_id=20,
            suggested_target_account_id=None,
        )
        decision = self._decide(parsed, derived, suggestion)
        assert decision.account_id == self.SESSION_ACCOUNT
        assert decision.target_account_id == 20

    # Transfer account routing — income where source == session account (cleared)
    def test_income_transfer_clears_source_if_same_as_session(self):
        parsed = _make_parsed(direction="income")
        derived = _make_derived(is_transfer_like=True)
        suggestion = _make_suggestion(
            suggested_operation_type="transfer",
            suggested_type="income",
            suggested_account_id=self.SESSION_ACCOUNT,  # same as session → None
        )
        decision = self._decide(parsed, derived, suggestion)
        assert decision.target_account_id is None

    # Non-transfer: account from enrichment or fallback
    def test_regular_uses_suggested_account_or_session(self):
        parsed = _make_parsed(raw_type="purchase")
        derived = _make_derived()
        suggestion = _make_suggestion(suggested_account_id=None, suggested_operation_type="regular")
        decision = self._decide(parsed, derived, suggestion)
        assert decision.account_id == self.SESSION_ACCOUNT


# ---------------------------------------------------------------------------
# Constants sanity check
# ---------------------------------------------------------------------------

class TestConstants:
    def test_credit_payment_keywords_non_empty(self):
        assert len(_CREDIT_PAYMENT_KEYWORDS) > 0
        assert "погашение кредита" in _CREDIT_PAYMENT_KEYWORDS

    def test_raw_types_requiring_split(self):
        assert "credit_payment" in _RAW_TYPES_REQUIRING_CREDIT_SPLIT
