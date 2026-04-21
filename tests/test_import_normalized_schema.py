"""Unit tests for app.schemas.import_normalized — Phase 1.2."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.import_normalized import (
    NORMALIZER_VERSION,
    NormalizedDataV2,
    TokensV2,
)
from app.services.import_normalizer_v2 import ExtractedTokens


# ---------------------------------------------------------------------------
# from_tokens — ExtractedTokens → NormalizedDataV2
# ---------------------------------------------------------------------------


def test_from_tokens_populates_all_fields() -> None:
    tokens = ExtractedTokens(
        phone="+79161234567",
        contract="1234567",
        iban="DE89370400440532013000",
        card="**** 1234",
        person_name="Иванов И.И.",
        counterparty_org='ООО "Рога и копыта"',
        amounts=(Decimal("1234.56"), Decimal("50.00")),
        dates=(date(2026, 3, 15),),
    )
    norm = NormalizedDataV2.from_tokens(
        tokens=tokens,
        skeleton="перевод <PHONE> <CONTRACT>",
        fingerprint="abcdef0123456789",
    )

    assert norm.skeleton == "перевод <PHONE> <CONTRACT>"
    assert norm.fingerprint == "abcdef0123456789"
    assert norm.normalizer_version == NORMALIZER_VERSION
    assert norm.tokens.phone == "+79161234567"
    assert norm.tokens.contract == "1234567"
    assert norm.tokens.iban == "DE89370400440532013000"
    assert norm.tokens.card == "**** 1234"
    assert norm.tokens.person_name_present is True
    assert norm.tokens.counterparty_org == 'ООО "Рога и копыта"'
    assert norm.tokens.amounts_extra == ["1234.56", "50.00"]
    assert norm.tokens.dates_extra == ["2026-03-15"]


def test_from_tokens_person_absent_sets_flag_false() -> None:
    tokens = ExtractedTokens(phone="+79161234567")
    norm = NormalizedDataV2.from_tokens(
        tokens=tokens, skeleton="s", fingerprint="f" * 16,
    )
    assert norm.tokens.person_name_present is False


def test_from_tokens_empty_produces_empty_collections() -> None:
    norm = NormalizedDataV2.from_tokens(
        tokens=ExtractedTokens(), skeleton="", fingerprint="0" * 16,
    )
    assert norm.tokens.amounts_extra == []
    assert norm.tokens.dates_extra == []
    assert norm.tokens.phone is None
    assert norm.tokens.person_name_present is False


# ---------------------------------------------------------------------------
# from_normalized_data / from_import_row
# ---------------------------------------------------------------------------


def test_from_normalized_data_none_when_empty() -> None:
    assert NormalizedDataV2.from_normalized_data(None) is None
    assert NormalizedDataV2.from_normalized_data({}) is None


def test_from_normalized_data_none_when_v1_only() -> None:
    v1 = {
        "description": "Покупка в Пятёрочке",
        "amount": "500.00",
        "type": "expense",
    }
    assert NormalizedDataV2.from_normalized_data(v1) is None


def test_from_normalized_data_parses_when_version_2() -> None:
    payload = {
        "description": "legacy v1 key",
        "normalizer_version": 2,
        "skeleton": "покупка в <ORG>",
        "fingerprint": "abcdef0123456789",
        "tokens": {
            "phone": None,
            "contract": None,
            "iban": None,
            "card": None,
            "person_name_present": False,
            "counterparty_org": "ООО Пятёрочка",
            "amounts_extra": [],
            "dates_extra": [],
        },
    }
    norm = NormalizedDataV2.from_normalized_data(payload)
    assert norm is not None
    assert norm.skeleton == "покупка в <ORG>"
    assert norm.tokens.counterparty_org == "ООО Пятёрочка"


def test_from_import_row_duck_typed() -> None:
    row = SimpleNamespace(normalized_data_json={
        "normalizer_version": 2,
        "skeleton": "s",
        "fingerprint": "f" * 16,
        "tokens": {},
    })
    norm = NormalizedDataV2.from_import_row(row)
    assert norm is not None
    assert norm.skeleton == "s"


def test_from_import_row_missing_attribute() -> None:
    row = SimpleNamespace()
    assert NormalizedDataV2.from_import_row(row) is None


def test_from_import_row_null_json() -> None:
    row = SimpleNamespace(normalized_data_json=None)
    assert NormalizedDataV2.from_import_row(row) is None


# ---------------------------------------------------------------------------
# merge_into
# ---------------------------------------------------------------------------


def test_merge_preserves_existing_v1_keys() -> None:
    existing = {
        "description": "Покупка",
        "amount": "500.00",
        "type": "expense",
        "account_id": 17,
    }
    norm = NormalizedDataV2.from_tokens(
        tokens=ExtractedTokens(phone="+79161234567"),
        skeleton="перевод <PHONE>",
        fingerprint="a" * 16,
    )
    merged = norm.merge_into(existing)

    # v1 keys untouched
    assert merged["description"] == "Покупка"
    assert merged["amount"] == "500.00"
    assert merged["type"] == "expense"
    assert merged["account_id"] == 17

    # v2 keys added
    assert merged["normalizer_version"] == 2
    assert merged["skeleton"] == "перевод <PHONE>"
    assert merged["fingerprint"] == "a" * 16
    assert merged["tokens"]["phone"] == "+79161234567"


def test_merge_into_none_returns_v2_only() -> None:
    norm = NormalizedDataV2.from_tokens(
        tokens=ExtractedTokens(),
        skeleton="s",
        fingerprint="f" * 16,
    )
    merged = norm.merge_into(None)
    assert merged["skeleton"] == "s"
    assert merged["fingerprint"] == "f" * 16
    assert merged["normalizer_version"] == 2


def test_merge_overwrites_stale_v2_keys() -> None:
    existing = {
        "description": "keep me",
        "normalizer_version": 2,
        "skeleton": "old skeleton",
        "fingerprint": "0" * 16,
        "tokens": {"phone": "+79990000000"},
    }
    norm = NormalizedDataV2.from_tokens(
        tokens=ExtractedTokens(phone="+79161234567"),
        skeleton="new skeleton",
        fingerprint="b" * 16,
    )
    merged = norm.merge_into(existing)

    assert merged["description"] == "keep me"
    assert merged["skeleton"] == "new skeleton"
    assert merged["fingerprint"] == "b" * 16
    assert merged["tokens"]["phone"] == "+79161234567"


def test_merge_does_not_mutate_input() -> None:
    existing = {"description": "x", "tokens": {"foo": "bar"}}
    norm = NormalizedDataV2.from_tokens(
        tokens=ExtractedTokens(), skeleton="s", fingerprint="f" * 16,
    )
    _ = norm.merge_into(existing)
    assert "skeleton" not in existing
    assert existing["tokens"] == {"foo": "bar"}


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


def test_json_round_trip_stable() -> None:
    tokens = ExtractedTokens(
        phone="+79161234567",
        contract="1234567",
        amounts=(Decimal("100.00"),),
        dates=(date(2026, 3, 15),),
    )
    norm = NormalizedDataV2.from_tokens(
        tokens=tokens, skeleton="test <PHONE>", fingerprint="c" * 16,
    )

    dumped = norm.model_dump()
    serialized = json.dumps(dumped)
    restored = NormalizedDataV2.model_validate(json.loads(serialized))

    assert restored == norm


def test_parse_ignores_unknown_keys() -> None:
    payload = {
        "normalizer_version": 2,
        "skeleton": "s",
        "fingerprint": "f" * 16,
        "tokens": {"phone": None, "extra_garbage": "ignored"},
        "random_future_key": 42,
    }
    norm = NormalizedDataV2.from_normalized_data(payload)
    assert norm is not None
    assert norm.skeleton == "s"
