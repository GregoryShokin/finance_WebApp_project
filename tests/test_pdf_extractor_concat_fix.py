"""Regression tests for the concatenated-line bug in pdf_extractor.

When pdfplumber merges multiple Yandex Credit transactions into a single text
line (a known artifact of mis-detected column boundaries on certain pages),
the prepass in `_parse_yandex_credit_rows` must split them into separate
ImportRows instead of collapsing into one row whose description is the
concatenation of all three.

Real example from session #177 (2026-04-22): three 14.02.2026 transactions
were merged into one row with description containing all three operations
and amount=+11361 (only the first amount kept). Two of those transactions
were silently lost.
"""
from __future__ import annotations

from app.services.import_extractors.pdf_extractor import PdfExtractor


def test_two_concatenated_transactions_split_into_two_rows():
    """Single broken line containing two complete inline transactions
    must produce two separate ImportRows."""
    line = (
        "Оплата товаров и услуг yandex*5399*market 14.02.2026 11 361,00 \u20bd 11 361,00 \u20bd "
        "Оплата товаров и услуг yandex*5399*market 14.02.2026 11 239,00 \u20bd 11 239,00 \u20bd"
    )
    rows, _ = PdfExtractor()._parse_yandex_credit_rows([line])
    assert len(rows) == 2
    amounts = sorted(r["amount"] for r in rows)
    assert amounts == ["-11239.00", "-11361.00"]
    assert all(r["date"] == "14.02.2026" for r in rows)


def test_session_177_three_transactions_with_dangling_description():
    """Exact line from session #177 — three logical transactions where the
    third (cancellation) has no trailing amount. Prepass must extract the
    two transactions that have full amount data; the third is lost (correct
    behaviour given the input has no amount for it)."""
    broken = (
        "Договора Оплата товаров и услуг yandex*5399*market 14.02.2026 11 361,00 \u20bd 11 361,00 \u20bd "
        "Оплата товаров и услуг yandex*5399*market 14.02.2026 11 239,00 \u20bd 11 239,00 \u20bd "
        "Отмена по операции Оплата товаров и услуг yandex*5399*market от 14.02.2026"
    )
    rows, _ = PdfExtractor()._parse_yandex_credit_rows([broken])
    assert len(rows) == 2, f"Expected 2 rows from concatenated line, got {len(rows)}"
    amounts = sorted(r["amount"] for r in rows)
    # Both purchases on 14.02 should be present
    assert "-11361.00" in amounts
    assert "-11239.00" in amounts


def test_clean_single_inline_line_unaffected_by_prepass():
    """The prepass only fires on lines with 2+ matches. A clean single-
    transaction line must continue to go through the existing INLINE path."""
    clean = "Оплата товаров и услуг yandex*5399*market 26.11.2025 17 540,00 \u20bd 17 540,00 \u20bd"
    rows, _ = PdfExtractor()._parse_yandex_credit_rows([clean])
    assert len(rows) == 1
    assert rows[0]["amount"] == "-17540.00"
    assert rows[0]["date"] == "26.11.2025"


def test_multiline_slow_path_unaffected_by_prepass():
    """When description and date+amount come on separate lines (typical PDF
    layout), the slow path must keep working — prepass leaves these alone."""
    lines = [
        "Оплата товаров и услуг yandex*5399*market",
        "26.11.2025 17 540,00 \u20bd 17 540,00 \u20bd",
    ]
    rows, _ = PdfExtractor()._parse_yandex_credit_rows(lines)
    assert len(rows) == 1
    assert rows[0]["amount"] == "-17540.00"


def test_empty_lines_produce_no_rows():
    rows, _ = PdfExtractor()._parse_yandex_credit_rows([])
    assert rows == []
    rows, _ = PdfExtractor()._parse_yandex_credit_rows([""])
    assert rows == []
