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
    is_refund_like,
    is_transfer_like,
    normalize_skeleton,
    pick_refund_brand,
    pick_transfer_identifier,
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


def test_whitespace_normalization_multiline_and_tabs() -> None:
    # Mixed NBSP, tabs, newlines — all collapsed by _prepare before regex runs.
    raw = "Перевод\tна\xa0+79161234567\nпо\r\nдоговору  №1234567"
    tokens = extract_tokens(raw)
    assert tokens.phone == "+79161234567"
    assert tokens.contract == "1234567"


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
# SBP merchant ID + payer card last4 (Brand registry §3, kind='sbp_merchant_id')
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,merchant,last4", [
    # Format A: explicit SBP — "MERCHANT_ID NSPK SBP CARD_LAST4"
    ("Покупка 26033 MOR SBP 0387 Volgodonsk", "26033", "0387"),
    ("Оплата 12345 MOP SBP 1232 Москва", "12345", "1232"),
    ("Платёж 999999 ABCDE SBP 9999", "999999", "9999"),
])
def test_extract_sbp_explicit_format(raw: str, merchant: str, last4: str) -> None:
    tokens = extract_tokens(raw)
    assert tokens.sbp_merchant_id == merchant
    assert tokens.card_last4 == last4


@pytest.mark.parametrize("raw,merchant,last4", [
    # Format B: card-via-QR — "NSPK MERCHANT_ID_P_QR CARD_LAST4"
    ("Оплата в QSR 26033_P_QR 1232", "26033", "1232"),
    ("Списание MOR 12345_P_QR 0387", "12345", "0387"),
])
def test_extract_sbp_qr_suffix_format(raw: str, merchant: str, last4: str) -> None:
    tokens = extract_tokens(raw)
    assert tokens.sbp_merchant_id == merchant
    assert tokens.card_last4 == last4


def test_no_sbp_when_pattern_absent() -> None:
    # Plain "TEXT NUMBER City RUS" form — number can be store-id or merchant-id
    # depending on the chain (Pyaterochka uses store-ids, QSR uses merchant-id)
    # so we deliberately don't extract from it.
    tokens = extract_tokens("Покупка PYATEROCHKA 14130 Volgodonsk RUS")
    assert tokens.sbp_merchant_id is None
    assert tokens.card_last4 is None


def test_sbp_skeleton_keeps_merchant_id_after_regex_change() -> None:
    raw = "Покупка 26033 MOR SBP 0387 Volgodonsk 250,00 руб"
    skel = normalize_skeleton(raw, extract_tokens(raw))
    assert "26033" in skel
    assert "<SBP_PAYMENT>" in skel.upper()
    assert "0387" not in skel


def test_sbp_qr_skeleton_keeps_merchant_id() -> None:
    raw = "Оплата в QSR 26033_P_QR 1232"
    skel = normalize_skeleton(raw, extract_tokens(raw))
    assert "26033" in skel
    assert "<SBP_PAYMENT>" in skel.upper()
    assert "1232" not in skel
    assert "_p_qr" not in skel


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


# ---------------------------------------------------------------------------
# Transfer-aware fingerprint (Phase И-08 bulk clusters, Этап 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("description,op,expected", [
    ("Внешний перевод по номеру телефона +79161234567", None, True),
    ("Перевод брату", None, True),
    ("Внутрибанковский перевод с договора 7001", None, True),
    ("Оплата в PYATEROCHKA 14130", None, False),
    ("Оплата Megafon", None, False),
    # operation_type signal alone is enough even without a keyword in the text.
    ("Списание", "transfer", True),
    # Case-insensitive & embedded-in-sentence.
    ("С карты на карту по заявке", None, True),
])
def test_is_transfer_like(description: str, op: str | None, expected: bool) -> None:
    assert is_transfer_like(description, op) is expected


def test_pick_transfer_identifier_priority() -> None:
    # Phone wins over contract and card when all are present.
    tokens = extract_tokens(
        "Перевод на +79161234567 по договору №7001 карта **** 9876"
    )
    assert pick_transfer_identifier(tokens) == ("phone", "+79161234567")


def test_pick_transfer_identifier_none_when_no_identifiers() -> None:
    tokens = extract_tokens("Перевод между своими")
    assert pick_transfer_identifier(tokens) is None


def test_transfer_fingerprint_splits_by_phone() -> None:
    """Two transfers to different phones → different fingerprints."""
    raw1 = "Внешний перевод по номеру телефона +79161234567"
    raw2 = "Внешний перевод по номеру телефона +79167654321"
    t1, t2 = extract_tokens(raw1), extract_tokens(raw2)
    s1 = normalize_skeleton(raw1, t1)
    s2 = normalize_skeleton(raw2, t2)
    # Skeletons collapse the phone to <PHONE>, so without transfer_identifier
    # they would share a fingerprint — that's the bug we're fixing.
    assert s1 == s2

    fp1 = fingerprint(
        "tbank", 1, "expense", s1, t1.contract,
        transfer_identifier=pick_transfer_identifier(t1),
    )
    fp2 = fingerprint(
        "tbank", 1, "expense", s2, t2.contract,
        transfer_identifier=pick_transfer_identifier(t2),
    )
    assert fp1 != fp2


def test_transfer_fingerprint_merges_same_phone() -> None:
    """Two transfers to the same phone → one fingerprint (same recipient)."""
    raw1 = "Перевод на +79161234567 15.03.2026 500,00"
    raw2 = "Перевод на +79161234567 20.04.2026 1 500,00"
    t1, t2 = extract_tokens(raw1), extract_tokens(raw2)
    s1 = normalize_skeleton(raw1, t1)
    s2 = normalize_skeleton(raw2, t2)
    fp1 = fingerprint(
        "tbank", 1, "expense", s1, t1.contract,
        transfer_identifier=pick_transfer_identifier(t1),
    )
    fp2 = fingerprint(
        "tbank", 1, "expense", s2, t2.contract,
        transfer_identifier=pick_transfer_identifier(t2),
    )
    assert fp1 == fp2


def test_nontransfer_merchant_rows_not_pulled_into_transfer_branch() -> None:
    """Merchant rows must not trigger transfer-identifier fingerprinting.

    The anti-regression guarantee for Этап 1: two Pyaterochka rows (even with
    bare TT numbers in the description) are classified as non-transfer, so
    their fingerprints are built without folding identifiers in raw form. The
    fact that different TT numbers live in different clusters here is a
    *separate* concern — Этап 2 (brand extractor) merges them at the
    brand-key layer, not at the fingerprint layer.
    """
    raw1 = "Оплата в PYATEROCHKA 14130 Volgodonsk RUS"
    raw2 = "Оплата в PYATEROCHKA 20046 Volgodonsk RUS"
    assert is_transfer_like(raw1, None) is False
    assert is_transfer_like(raw2, None) is False
    t1, t2 = extract_tokens(raw1), extract_tokens(raw2)
    assert pick_transfer_identifier(t1) is None
    assert pick_transfer_identifier(t2) is None


def test_transfer_identifier_does_not_double_include_contract() -> None:
    """When transfer_identifier=('contract', X), positional `contract` is ignored."""
    # Same contract value fed via both paths — result must equal the
    # identifier-only call (i.e. not the sum of both).
    fp_identifier_only = fingerprint(
        "tbank", 1, "income", "skel",
        transfer_identifier=("contract", "A-1"),
    )
    fp_both = fingerprint(
        "tbank", 1, "income", "skel", contract="A-1",
        transfer_identifier=("contract", "A-1"),
    )
    assert fp_identifier_only == fp_both


def test_transfer_fingerprint_vs_payment_fingerprint_diverge() -> None:
    """Transfer to Megafon phone vs merchant payment to Megafon → different fp.

    The payment is not transfer-like (no 'перевод' keyword, operation_type is
    not 'transfer'), so its identifier is swallowed by the skeleton. The
    actual transfer feeds the phone into the fingerprint raw. Different
    payloads → different fingerprints, which is exactly what we want.
    """
    transfer_desc = "Внешний перевод по номеру телефона +79161234567"
    payment_desc = "Оплата Megafon +79161234567"

    t_transfer = extract_tokens(transfer_desc)
    t_payment = extract_tokens(payment_desc)
    s_transfer = normalize_skeleton(transfer_desc, t_transfer)
    s_payment = normalize_skeleton(payment_desc, t_payment)

    fp_transfer = fingerprint(
        "tbank", 1, "expense", s_transfer, t_transfer.contract,
        transfer_identifier=pick_transfer_identifier(t_transfer)
        if is_transfer_like(transfer_desc, None) else None,
    )
    fp_payment = fingerprint(
        "tbank", 1, "expense", s_payment, t_payment.contract,
        transfer_identifier=pick_transfer_identifier(t_payment)
        if is_transfer_like(payment_desc, None) else None,
    )
    assert fp_transfer != fp_payment


# ---------------------------------------------------------------------------
# Refund detection — И-09
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("desc", [
    "Отмена операции оплаты KOFEMOLOKO Volgodonsk RUS",
    "Отмена оплаты SBERMARKET 240 RUB",
    "Возврат покупки в магазине «Пятёрочка»",
    "Возврат средств от OZON",
    "REFUND ALIEXPRESS",
    "Chargeback T-Bank",
    "Reversal operation 15.03.2026",
])
def test_is_refund_like_positive(desc: str) -> None:
    assert is_refund_like(desc) is True


@pytest.mark.parametrize("desc", [
    "Покупка в магазине «Пятёрочка»",
    "Перевод +79161234567",
    "Оплата услуг МТС",
    "Зарплата от ООО «Ромашка»",
])
def test_is_refund_like_negative(desc: str) -> None:
    assert is_refund_like(desc) is False


def test_is_refund_like_honors_operation_type() -> None:
    # If upstream already classified the row as refund, the flag wins even
    # when the description lacks a keyword.
    assert is_refund_like("Поступление от продавца", "refund") is True


def test_refund_excluded_from_transfer_detection() -> None:
    # A row starting with "Отмена операции" shouldn't be pulled into the
    # identifier-aware transfer branch even if it mentions a phone.
    desc = "Отмена операции оплаты KOFEMOLOKO"
    assert is_transfer_like(desc, None) is False
    assert is_refund_like(desc, None) is True


def test_pick_refund_brand_known_merchant() -> None:
    # Classic refund line: keyword + merchant + locale. Brand should be the
    # merchant token, not the keyword or locale.
    brand = pick_refund_brand("Отмена операции оплаты KOFEMOLOKO Volgodonsk RUS")
    assert brand == "kofemoloko"


def test_pick_refund_brand_strips_refund_keyword() -> None:
    # The refund keyword itself must never become the brand.
    brand = pick_refund_brand("Возврат OZON 1250 RUB")
    assert brand == "ozon"


def test_pick_refund_brand_returns_none_when_no_merchant() -> None:
    # Only noise tokens after the refund keyword → nothing extractable.
    assert pick_refund_brand("Отмена операции") is None
