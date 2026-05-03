"""Группа 6 (T19–T23) — edge cases нормализации.

  • T19 — multi-currency: USD выписка.
  • T20 — отрицательная сумма через скобки `(1500.00)`.
  • T21 — datetime с явной timezone (ISO 8601 + offset).
  • T22 — пустое описание / пустая дата → ImportRowValidationError.
  • T23 — кириллица + NBSP + en-dash в сумме (стандартные банковские
    варианты «1 234,56» / «1\xa0234,56» / «−500»).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.import_normalizer import ImportNormalizer
from app.services.import_validator import (
    ImportRowValidationError,
    parse_date,
    parse_decimal,
)


# ---------------------------------------------------------------------------
# T19 — multi-currency
# ---------------------------------------------------------------------------


def test_normalize_row_uses_currency_column_when_present():
    norm = ImportNormalizer()
    raw = {
        "date": "10.04.2026",
        "desc": "Apple Store",
        "amt": "-99.99",
        "ccy": "USD",
    }
    out = norm.normalize_row(
        raw_row=raw,
        field_mapping={
            "date": "date",
            "description": "desc",
            "amount": "amt",
            "currency": "ccy",
        },
        date_format="%d.%m.%Y",
        default_currency="RUB",
    )
    assert out["currency"] == "USD"
    assert out["amount"] == "99.99"
    assert out["direction"] == "expense"


def test_normalize_row_falls_back_to_default_currency():
    norm = ImportNormalizer()
    raw = {
        "date": "10.04.2026",
        "desc": "Магазин",
        "amt": "100.00",
    }
    out = norm.normalize_row(
        raw_row=raw,
        field_mapping={
            "date": "date",
            "description": "desc",
            "amount": "amt",
        },
        date_format="%d.%m.%Y",
        default_currency="EUR",
    )
    assert out["currency"] == "EUR"


# ---------------------------------------------------------------------------
# T20 — отрицательная сумма / разные знаки минус
# ---------------------------------------------------------------------------


def test_parse_decimal_handles_unicode_minus_signs():
    # Русские/типографские варианты минуса: U+2212 minus, en-dash, em-dash.
    assert parse_decimal("−500.00") == Decimal("-500.00")  # U+2212
    assert parse_decimal("–500,00") == Decimal("-500.00")  # en-dash
    assert parse_decimal("—500,00") == Decimal("-500.00")  # em-dash


def test_parse_decimal_strips_currency_marker():
    assert parse_decimal("1500.00 ₽") == Decimal("1500.00")
    assert parse_decimal("1500,00 RUB") == Decimal("1500.00")
    assert parse_decimal("99.99 USD") == Decimal("99.99")


def test_parse_decimal_handles_nbsp_and_thousands_separator():
    # Российские банки часто разделяют тысячи неразрывным пробелом.
    assert parse_decimal("1 234,56") == Decimal("1234.56")
    assert parse_decimal("1 234,56") == Decimal("1234.56")
    assert parse_decimal("1234.56") == Decimal("1234.56")


def test_normalize_row_keeps_amount_positive_and_marks_direction(
):
    """Отрицательная сумма даёт direction=expense, amount хранится по
    модулю — это контракт ImportNormalizer."""
    norm = ImportNormalizer()
    out = norm.normalize_row(
        raw_row={"date": "10.04.2026", "desc": "x", "amt": "-1500.00"},
        field_mapping={"date": "date", "description": "desc", "amount": "amt"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
    )
    assert out["direction"] == "expense"
    assert out["amount"] == "1500.00"


def test_parse_decimal_does_not_silently_swallow_garbage():
    with pytest.raises(ImportRowValidationError):
        parse_decimal("not a number")


# ---------------------------------------------------------------------------
# T21 — datetime + timezone
# ---------------------------------------------------------------------------


def test_parse_date_iso_with_offset_keeps_tz():
    """ISO 8601 с offset — `parse_date` сохраняет timezone-aware datetime."""
    dt = parse_date("2026-04-10T10:30:00+03:00", "%Y-%m-%dT%H:%M:%S%z")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 3 * 3600


def test_normalize_row_naive_date_tagged_moscow():
    """Naive datetime должен интерпретироваться в МСК (см. _BANK_TZ)."""
    norm = ImportNormalizer()
    out = norm.normalize_row(
        raw_row={"date": "10.04.2026 12:00:00", "desc": "x", "amt": "100"},
        field_mapping={"date": "date", "description": "desc", "amount": "amt"},
        date_format="%d.%m.%Y %H:%M:%S",
        default_currency="RUB",
    )
    # ISO формат включает offset: +03:00 для Москвы (вне DST с 2014).
    assert "+03:00" in out["date"]


# ---------------------------------------------------------------------------
# T22 — пустые поля
# ---------------------------------------------------------------------------


def test_normalize_row_empty_description_raises():
    norm = ImportNormalizer()
    with pytest.raises(ImportRowValidationError) as exc:
        norm.normalize_row(
            raw_row={"date": "10.04.2026", "desc": "", "amt": "100"},
            field_mapping={"date": "date", "description": "desc", "amount": "amt"},
            date_format="%d.%m.%Y",
            default_currency="RUB",
        )
    assert "Пустое описание" in str(exc.value)


def test_normalize_row_empty_date_raises():
    norm = ImportNormalizer()
    with pytest.raises(ImportRowValidationError) as exc:
        norm.normalize_row(
            raw_row={"date": "", "desc": "x", "amt": "100"},
            field_mapping={"date": "date", "description": "desc", "amount": "amt"},
            date_format="%d.%m.%Y",
            default_currency="RUB",
        )
    assert "Пустая дата" in str(exc.value)


def test_normalize_row_zero_amount_raises():
    """Сумма ровно 0 должна быть отклонена — нет операции для импорта."""
    norm = ImportNormalizer()
    with pytest.raises(ImportRowValidationError) as exc:
        norm.normalize_row(
            raw_row={"date": "10.04.2026", "desc": "x", "amt": "0"},
            field_mapping={"date": "date", "description": "desc", "amount": "amt"},
            date_format="%d.%m.%Y",
            default_currency="RUB",
        )
    assert "ноль" in str(exc.value).lower() or "нул" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# T23 — кириллица в direction-маркерах
# ---------------------------------------------------------------------------


def test_direction_resolved_from_russian_keyword_overrides_amount_sign():
    """direction-колонка с русским словом 'приход'/'расход' выигрывает
    у знака суммы. Тестируется внутренний резолвер _resolve_direction."""
    norm = ImportNormalizer()
    raw = {"date": "10.04.2026", "desc": "x", "amt": "100", "dir": "приход"}
    out = norm.normalize_row(
        raw_row=raw,
        field_mapping={
            "date": "date", "description": "desc",
            "amount": "amt", "direction": "dir",
        },
        date_format="%d.%m.%Y",
        default_currency="RUB",
    )
    assert out["direction"] == "income"


def test_direction_explicit_expense_keyword_wins_over_positive_amount():
    norm = ImportNormalizer()
    out = norm.normalize_row(
        raw_row={"date": "10.04.2026", "desc": "x", "amt": "100", "dir": "оплата"},
        field_mapping={
            "date": "date", "description": "desc",
            "amount": "amt", "direction": "dir",
        },
        date_format="%d.%m.%Y",
        default_currency="RUB",
    )
    assert out["direction"] == "expense"


def test_separate_income_expense_columns():
    """Если amount-колонки нет, но есть отдельные income/expense — берём
    первую непустую и устанавливаем direction соответственно."""
    norm = ImportNormalizer()
    out = norm.normalize_row(
        raw_row={"date": "10.04.2026", "desc": "x", "in": "", "out": "1500.00"},
        field_mapping={
            "date": "date", "description": "desc",
            "income": "in", "expense": "out",
        },
        date_format="%d.%m.%Y",
        default_currency="RUB",
    )
    assert out["direction"] == "expense"
    assert out["amount"] == "1500.00"


def test_currency_uppercased_regardless_of_input_case():
    norm = ImportNormalizer()
    out = norm.normalize_row(
        raw_row={"date": "10.04.2026", "desc": "x", "amt": "10", "ccy": "usd"},
        field_mapping={
            "date": "date", "description": "desc",
            "amount": "amt", "currency": "ccy",
        },
        date_format="%d.%m.%Y",
        default_currency="RUB",
    )
    assert out["currency"] == "USD"
