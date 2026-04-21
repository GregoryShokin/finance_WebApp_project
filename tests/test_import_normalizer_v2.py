"""Unit tests for app.services.import_normalizer_v2 — Phase 1.1.

Synthetic inputs only; raw-fixture tests land in Phase 1.4.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.import_normalizer_v2 import (
    ExtractedTokens,
    extract_tokens,
    fingerprint,
    normalize_skeleton,
)


# ---------------------------------------------------------------------------
# Phones
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("Перевод на +79161234567", "+79161234567"),
    ("Перевод на 89161234567", "+79161234567"),
    ("Перевод на +7 (916) 123-45-67", "+79161234567"),
    ("Перевод на 8 916 123 45 67", "+79161234567"),
])
def test_extract_phone_formats(raw: str, expected: str) -> None:
    assert extract_tokens(raw).phone == expected


def test_no_phone_when_absent() -> None:
    assert extract_tokens("Покупка в магазине «Пятёрочка»").phone is None


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [
    ("Оплата по №1234567", "1234567"),
    ("Платёж по № 1234567", "1234567"),
    ("Поступление договор 7654321", "7654321"),
    ("Списание договор №ABC-1234", "ABC-1234"),
    ("contract_id=9988776", "9988776"),
    ("contract id: ABC-99-11", "ABC-99-11"),
])
def test_extract_contract_formats(raw: str, expected: str) -> None:
    assert extract_tokens(raw).contract == expected


def test_no_contract_for_bare_numbers() -> None:
    # Bare digits without the "№" / "договор" / "contract_id" prefix → nothing.
    assert extract_tokens("Перевод 500 рублей").contract is None


# ---------------------------------------------------------------------------
# IBAN
# ---------------------------------------------------------------------------


def test_extract_iban() -> None:
    raw = "Перевод на счёт DE89370400440532013000 в Deutsche Bank"
    assert extract_tokens(raw).iban == "DE89370400440532013000"


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "Оплата картой **** 1234",
    "Покупка *1234 в магазине",
    "Списание 1234 5678 9012 3456",
    "Списание 1234-5678-9012-3456",
])
def test_extract_card_formats(raw: str) -> None:
    assert extract_tokens(raw).card is not None


# ---------------------------------------------------------------------------
# Person name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,must_contain", [
    ("Перевод от Иванов И.И.",       "Иванов"),
    ("От И.И. Иванов поступление",   "Иванов"),
    ("Перевод от Иванов Иван Иванович", "Иванов"),
])
def test_extract_person_name(raw: str, must_contain: str) -> None:
    got = extract_tokens(raw).person_name
    assert got is not None
    assert must_contain in got


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,must_start", [
    ('Оплата ООО "Рога и копыта"', "ООО"),
    ("Оплата ИП Иванов", "ИП"),
    ("Платёж ПАО Сбербанк", "ПАО"),
])
def test_extract_org(raw: str, must_start: str) -> None:
    got = extract_tokens(raw).counterparty_org
    assert got is not None and got.startswith(must_start)


# ---------------------------------------------------------------------------
# Amounts & dates
# ---------------------------------------------------------------------------


def test_extract_amounts() -> None:
    tokens = extract_tokens("Платёж 1 234,56 руб и комиссия 50,00 руб")
    assert tokens.amounts == (Decimal("1234.56"), Decimal("50.00"))


def test_extract_dates_both_formats() -> None:
    tokens = extract_tokens("Операция от 15.03.2026, книжная 2026-03-20")
    assert date(2026, 3, 15) in tokens.dates
    assert date(2026, 3, 20) in tokens.dates


def test_invalid_date_is_skipped() -> None:
    tokens = extract_tokens("Сбой 32.13.2026")
    assert tokens.dates == ()


# ---------------------------------------------------------------------------
# Skeleton
# ---------------------------------------------------------------------------


def test_skeleton_replaces_all_placeholders() -> None:
    raw = "Перевод на +79161234567 по договору №1234567 сумма 1 500,00 руб от 15.03.2026"
    tokens = extract_tokens(raw)
    skel = normalize_skeleton(raw, tokens)
    assert "<PHONE>" in skel
    assert "<CONTRACT>" in skel
    assert "<AMOUNT>" in skel
    assert "<DATE>" in skel
    # Stop-words drop out.
    assert " от " not in f" {skel} "
    assert "руб" not in skel.split()


def test_skeleton_lowercases_regular_words() -> None:
    raw = "Покупка в Пятёрочке"
    skel = normalize_skeleton(raw, extract_tokens(raw))
    assert skel == "покупка в пятёрочке"


def test_skeleton_strips_punctuation_preserves_placeholders() -> None:
    raw = "Оплата, картой **** 1234!"
    skel = normalize_skeleton(raw, extract_tokens(raw))
    assert "<CARD>" in skel
    assert "," not in skel and "!" not in skel


def test_skeleton_idempotent() -> None:
    raw = "Перевод от Иванов И.И. по договору №1234567 на 500,00 руб"
    tokens = extract_tokens(raw)
    once = normalize_skeleton(raw, tokens)
    twice = normalize_skeleton(once, extract_tokens(once))
    assert once == twice


def test_empty_description() -> None:
    assert extract_tokens("") == ExtractedTokens()
    assert normalize_skeleton("", ExtractedTokens()) == ""


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic() -> None:
    fp1 = fingerprint("tbank", 42, "expense", "оплата <ORG>")
    fp2 = fingerprint("tbank", 42, "expense", "оплата <ORG>")
    assert fp1 == fp2
    assert len(fp1) == 16


def test_fingerprint_changes_on_any_input() -> None:
    base = fingerprint("tbank", 42, "expense", "оплата <ORG>")
    assert fingerprint("yandex_bank", 42, "expense", "оплата <ORG>") != base
    assert fingerprint("tbank", 43, "expense", "оплата <ORG>") != base
    assert fingerprint("tbank", 42, "income", "оплата <ORG>") != base
    assert fingerprint("tbank", 42, "expense", "оплата другое") != base


def test_fingerprint_contract_included_only_when_present() -> None:
    no_contract = fingerprint("tbank", 42, "expense", "skel")
    contract_none = fingerprint("tbank", 42, "expense", "skel", contract=None)
    contract_a = fingerprint("tbank", 42, "expense", "skel", contract="A-1")
    contract_b = fingerprint("tbank", 42, "expense", "skel", contract="A-2")

    assert no_contract == contract_none        # None is equivalent to absent
    assert contract_a != no_contract           # contract does affect fp
    assert contract_a != contract_b            # different contracts diverge


def test_fingerprint_same_contract_two_rows_same_fp() -> None:
    # Cluster invariant: same bank/account/direction/skeleton/contract → same cluster.
    raw1 = "Перевод по договору №7001 от Иванов И.И. 500,00 руб 15.03.2026"
    raw2 = "Перевод по договору №7001 от Петров П.П. 500,00 руб 20.03.2026"
    t1, t2 = extract_tokens(raw1), extract_tokens(raw2)
    s1 = normalize_skeleton(raw1, t1)
    s2 = normalize_skeleton(raw2, t2)
    # Skeletons should match — names/dates/amounts are placeholdered.
    assert s1 == s2
    assert (
        fingerprint("tbank", 1, "income", s1, t1.contract)
        == fingerprint("tbank", 1, "income", s2, t2.contract)
    )


def test_fingerprint_different_contract_different_fp() -> None:
    raw1 = "Перевод по договору №7001 от Иванов И.И. 500,00 руб"
    raw2 = "Перевод по договору №7002 от Иванов И.И. 500,00 руб"
    t1, t2 = extract_tokens(raw1), extract_tokens(raw2)
    s1 = normalize_skeleton(raw1, t1)
    s2 = normalize_skeleton(raw2, t2)
    assert (
        fingerprint("tbank", 1, "income", s1, t1.contract)
        != fingerprint("tbank", 1, "income", s2, t2.contract)
    )
