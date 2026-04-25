"""Naive datetimes parsed from bank statements (Т-Банк, Я-Банк, Озон) must
be tagged with Europe/Moscow, not UTC. Tagging МСК time as UTC pushed dates
near midnight to the next day in the user's display timezone (UI shifted
13.03 23:14 МСК → 14.03 02:14 МСК) and broke the cross-bank transfer matcher
windowing because two halves of one transfer ended up with timestamps 3
hours apart in the stored value.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from app.services.import_normalizer import ImportNormalizer


def _normalize(date_raw: str) -> str:
    norm = ImportNormalizer()
    raw_row = {"date": date_raw, "description": "x", "amount": "100.00"}
    field_mapping = {"date": "date", "description": "description", "amount": "amount"}
    result = norm.normalize_row(
        raw_row=raw_row,
        field_mapping=field_mapping,
        date_format="%d.%m.%Y %H:%M",
        default_currency="RUB",
    )
    return result["date"]


def test_naive_datetime_is_tagged_moscow_not_utc():
    """13.03.2026 23:14 in a Russian bank statement is МСК, not UTC."""
    iso = _normalize("13.03.2026 23:14")
    assert iso == "2026-03-13T23:14:00+03:00"
    # Sanity: this is NOT 14.03 once converted to a date.
    assert iso.startswith("2026-03-13")


def test_naive_datetime_does_not_drift_to_next_day_at_midnight():
    """Late-evening МСК transactions used to bleed into the next UTC day."""
    iso = _normalize("01.04.2026 23:50")
    # In МСК: 01.04 23:50. Same datetime in UTC: 01.04 20:50 — same date.
    assert iso == "2026-04-01T23:50:00+03:00"


def test_already_aware_datetime_is_kept_intact():
    """If the raw row already carries TZ info, the normalizer must not relabel it."""
    norm = ImportNormalizer()
    raw_row = {"date": "2026-03-13T23:14:00+05:00", "description": "x", "amount": "100"}
    field_mapping = {"date": "date", "description": "description", "amount": "amount"}
    result = norm.normalize_row(
        raw_row=raw_row,
        field_mapping=field_mapping,
        date_format="%Y-%m-%dT%H:%M:%S%z",
        default_currency="RUB",
    )
    # Offset preserved as-is — we don't override an explicit TZ.
    assert "+05:00" in result["date"] or result["date"].endswith("+0500")


def test_moscow_tz_is_3_hours_ahead_of_utc():
    """Sanity check on the constant — Europe/Moscow is UTC+3 year-round."""
    from datetime import datetime
    moscow = ZoneInfo("Europe/Moscow")
    sample = datetime(2026, 3, 13, 23, 14, tzinfo=moscow)
    assert sample.utcoffset().total_seconds() == 3 * 3600
