"""Regression tests for Sber statement_account_number extraction.

Sber renders the 20-digit РФ account number in groups separated by spaces
(«Номер счёта 40817 810 2 5209 5260514») and uses the heading «Номер счёта»
WITHOUT the word «лицевого». Prior to this patch the extractor's regex
matched only «Номер лицевого счёта» / «лицевого счёта», so every Sber
statement returned `statement_account_number=None`, which in turn meant
no account auto-match and the bank-supported guard could never fire on
Sber uploads.

Tests pin three branches:
  1. Sber-style heading with whitespace-grouped digits → normalized to a
     bare 20-digit string at confidence ≥ 0.95.
  2. Ozon-style heading «Номер лицевого счёта №…» continues to match
     (regression — must not break the existing positive cases).
  3. Negative cases: heading without a number, partial number, and
     plausible-but-wrong-length digit runs are all rejected.
"""
from __future__ import annotations

import pytest

from app.services.import_extractors.pdf_extractor import PdfExtractor


# ─── 1. Sber heading ────────────────────────────────────────────────────────


def test_sber_heading_extracts_20_digit_account():
    raw_lines = [
        "ПАО Сбербанк",
        "Выписка по счёту дебетовой карты",
        "Владелец счёта",
        "Шокин Павел Александрович",
        "Номер счёта 40817 810 2 5209 5260514",
        "Карта МИР Классическая •••• 7123",
        "Дата операции",  # stop-marker — header_lines breaks here
    ]
    account, reason, confidence = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account == "40817810252095260514"
    assert confidence is not None
    assert confidence >= 0.95
    assert reason  # non-empty Russian description, exact wording not pinned


def test_sber_heading_with_extra_punctuation_still_extracts():
    """Punctuation around the heading must not break the match."""
    raw_lines = [
        "Номер счёта: 40817 810 2 5209 5260514",
        "Дата операции",
    ]
    account, _, _ = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account == "40817810252095260514"


# ─── 2. Ozon-style regression ───────────────────────────────────────────────


def test_ozon_style_lichevogo_account_still_extracts():
    """Pre-patch behavior: «Номер лицевого счёта №…» must keep working."""
    raw_lines = [
        "Справка о движении средств",
        "Номер лицевого счёта №40817810700006095914 от 02.05.2026",
        "Дата операции",
    ]
    account, _, _ = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account == "40817810700006095914"


def test_ozon_style_lowercase_lichevogo_account_still_extracts():
    raw_lines = [
        "лицевого счёта: 40817810700006095914",
        "Дата операции",
    ]
    account, _, _ = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account == "40817810700006095914"


# ─── 3. Negative cases ──────────────────────────────────────────────────────


def test_no_number_after_heading_returns_none():
    raw_lines = [
        "Номер счёта",
        "Дата операции",
    ]
    account, reason, confidence = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account is None
    assert reason is None
    assert confidence is None


def test_partial_account_number_rejected():
    """A 12-digit number after «Номер счёта» is NOT an РФ лицевой счёт
    (regulator mandates 20 digits) — reject rather than return a half-match."""
    raw_lines = [
        "Номер счёта 40817 810 25",
        "Дата операции",
    ]
    account, _, _ = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account is None


def test_heading_inside_transaction_rows_is_not_matched():
    """The walker's stop_markers must terminate the header window before
    the transactions table; a stray «Номер счёта» mention there must not
    be considered a candidate.
    """
    raw_lines = [
        "Владелец счёта",
        "Шокин Павел Александрович",
        "Номер счёта 40817 810 2 5209 5260514",
        "Дата операции",  # <- terminates header window
        "01.05.2026 Номер счёта 11111 222 3 4444 5555555 — junk after stop",
    ]
    account, _, _ = PdfExtractor._extract_statement_account_number_details(raw_lines)
    # First match wins — must be the legitimate header, not the post-stop one.
    assert account == "40817810252095260514"


def test_text_with_digits_but_not_account_is_rejected():
    """«Номер счёта операции 12345» must not match — the regex requires the
    capture group to start with a digit immediately after the heading."""
    raw_lines = [
        "Номер счёта операции 12345 — служебный реквизит",
        "Дата операции",
    ]
    account, _, _ = PdfExtractor._extract_statement_account_number_details(raw_lines)
    assert account is None


# ─── normalizer unit-tests ──────────────────────────────────────────────────


@pytest.mark.parametrize("raw, expected", [
    ("40817 810 2 5209 5260514", "40817810252095260514"),
    ("40817810700006095914", "40817810700006095914"),
    ("  40817 810 2 5209 5260514  ", "40817810252095260514"),
    # Mixed alphanumeric (Yandex-like) — 20-digit rule doesn't apply, falls
    # back to the generic "len >= 8 + has_digit" branch.
    ("Э20240626883885586", "Э20240626883885586"),
])
def test_normalizer_accepts_valid_candidates(raw, expected):
    assert PdfExtractor._normalize_statement_account_candidate(raw) == expected


@pytest.mark.parametrize("raw", [
    None,
    "",
    "   ",
    "12345",                          # too short, all-digit
    "40817 810 25",                   # 10 digits — not a 20-digit account
    "40817810252095260514999",        # 23 digits — not a 20-digit account
    "исх. 1234567",                   # outgoing-mail prefix is not an account
])
def test_normalizer_rejects_invalid_candidates(raw):
    assert PdfExtractor._normalize_statement_account_candidate(raw) is None
