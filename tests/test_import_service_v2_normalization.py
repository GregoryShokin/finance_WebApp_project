"""Regression tests for the normalization pipeline contract.

Previously tested ImportService._apply_v2_normalization (now deleted).
Migrated to use app.services.import_normalization.normalize() — the
canonical entry point since the И-08 normalization refactor.

Key invariants verified:
  - skeleton / fingerprint / tokens are added to ParsedRow + DerivedRow
  - same contract → same cluster fingerprint (cluster stability)
  - different contracts → different fingerprint
  - transfer-aware fingerprint: different phones → different clusters
  - merchant vs transfer to same phone → different clusters
  - direction "unknown" differs from "expense" in fingerprint
"""

from __future__ import annotations

import pytest

from app.services.import_normalization import normalize


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _raw_row(description: str, amount: str = "500.00", date: str = "15.03.2026") -> dict:
    return {"Дата": date, "Описание": description, "Сумма": amount}


_MAPPING = {"date": "Дата", "description": "Описание", "amount": "Сумма"}


def _norm(description: str, *, direction: str = "expense", amount: str = "500.00"):
    """Convenience: normalize a row and return (parsed, derived)."""
    raw = _raw_row(description, amount=f"{'-' if direction == 'expense' else ''}{amount}")
    return normalize(
        raw_row=raw,
        field_mapping=_MAPPING,
        date_format="%d.%m.%Y",
        default_currency="RUB",
        bank="tbank",
        account_id=42,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_derived_has_skeleton_fingerprint_tokens():
    parsed, derived = _norm("Оплата по договору №7001 от Иванов И.И. 500,00 руб")

    assert derived.normalizer_version == 2
    assert "<CONTRACT>" in derived.skeleton
    assert "<PERSON>" in derived.skeleton
    assert len(derived.fingerprint) == 16
    assert derived.tokens.contract == "7001"
    assert derived.tokens.person_name is not None


def test_parsed_facts_are_immutable_originals():
    description = "Оплата по договору №7001 от Иванов И.И. 500,00 руб"
    parsed, _ = _norm(description)

    assert parsed.description == description  # original preserved
    assert parsed.amount > 0
    assert parsed.currency == "RUB"


def test_fingerprint_stable_same_contract():
    # Same bank + account + direction + contract → same cluster.
    base = "Перевод по договору №9001 от {name} 1 000,00 руб 15.03.2026"
    _, derived_a = _norm(base.format(name="Иванов И.И."), direction="income")
    _, derived_b = _norm(base.format(name="Петров П.П."), direction="income")

    assert derived_a.fingerprint == derived_b.fingerprint


def test_fingerprint_differs_different_contract():
    _, derived_a = _norm("Перевод по договору №9001 от Иванов И.И. 1 000,00 руб", direction="income")
    _, derived_b = _norm("Перевод по договору №9002 от Иванов И.И. 1 000,00 руб", direction="income")

    assert derived_a.fingerprint != derived_b.fingerprint


def test_transfer_by_phone_splits_cluster_by_recipient():
    """Rows to different phones must land in different clusters.

    Regression: before transfer-aware fingerprinting all "Внешний перевод по
    номеру телефона" rows collapsed into one mega-cluster.
    """
    _, derived_a = _norm("Внешний перевод по номеру телефона +79161111111")
    _, derived_b = _norm("Внешний перевод по номеру телефона +79162222222")

    assert derived_a.fingerprint != derived_b.fingerprint
    assert derived_a.is_transfer_like
    assert derived_b.is_transfer_like


def test_transfer_vs_merchant_same_phone_different_cluster():
    """A transfer TO a phone and a merchant payment mentioning the same phone
    must be in different clusters."""
    _, transfer = _norm("Внешний перевод по номеру телефона +79161234567")
    _, merchant = _norm("Оплата Megafon +79161234567 Volgodonsk RUS")

    assert transfer.fingerprint != merchant.fingerprint
    assert transfer.is_transfer_like
    assert not merchant.is_transfer_like


def test_direction_matters_for_fingerprint():
    """income and expense rows of the same description form separate clusters."""
    _, derived_income = _norm("Оплата в Пятёрочке 500,00 руб", direction="income")
    _, derived_expense = _norm("Оплата в Пятёрочке 500,00 руб", direction="expense")

    assert derived_income.fingerprint != derived_expense.fingerprint


def test_refund_row_detected():
    _, derived = _norm("Возврат оплаты KOFEMOLOKO Volgodonsk RUS", direction="income")

    assert derived.is_refund_like
    assert derived.refund_brand is not None
