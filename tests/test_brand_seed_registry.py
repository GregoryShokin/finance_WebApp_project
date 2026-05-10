"""Integration tests for scripts/seed_brand_registry.py and data/brands_seed_v1.csv.

These are pure CSV-parsing tests — no DB, no ORM. They verify that the seed
data has the entries and patterns required by the Brand Registry spec.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.seed_brand_registry import parse_patterns_field

CSV_PATH = Path("data/brands_seed_v1.csv")


def _load_seed_rows() -> list[dict[str, str]]:
    import csv
    with open(CSV_PATH, encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _patterns_for_slug(slug: str) -> list[tuple[str, str, bool]]:
    """Return [(kind, value, is_regex), …] for the given slug row."""
    rows = _load_seed_rows()
    for row in rows:
        if row["slug"] == slug:
            return parse_patterns_field(row.get("patterns") or "")
    raise KeyError(f"slug {slug!r} not found in {CSV_PATH}")


# ---------------------------------------------------------------------------
# Generic Яндекс brand — must exist with text patterns for the base name
# ---------------------------------------------------------------------------

def test_yandex_generic_brand_exists_in_seed() -> None:
    slugs = {row["slug"] for row in _load_seed_rows()}
    assert "yandex" in slugs, (
        "Generic 'yandex' brand must be seeded so 'оплата сервиса яндекс' "
        "can be resolved. Add: yandex,Яндекс,Сервисы,text:yandex|text:яндекс"
    )


@pytest.mark.parametrize("expected_text_pattern", ["yandex", "яндекс"])
def test_yandex_generic_brand_has_base_text_patterns(
    expected_text_pattern: str,
) -> None:
    patterns = _patterns_for_slug("yandex")
    text_values = {v for kind, v, _ in patterns if kind == "text"}
    assert expected_text_pattern in text_values, (
        f"Generic yandex brand is missing text pattern {expected_text_pattern!r}. "
        f"Found text patterns: {text_values}"
    )


def test_yandex_generic_brand_has_no_sbp_merchant_id() -> None:
    """Generic Yandex must not grab SBP merchant IDs — those belong to sub-brands."""
    patterns = _patterns_for_slug("yandex")
    sbp_ids = [v for kind, v, _ in patterns if kind == "sbp_merchant_id"]
    assert not sbp_ids, (
        f"Generic yandex brand must not carry sbp_merchant_id patterns: {sbp_ids}"
    )


# ---------------------------------------------------------------------------
# No slug may have "sbp" / "сбп" as a text-kind pattern value
# ---------------------------------------------------------------------------

def test_no_seed_brand_has_sbp_as_text_pattern() -> None:
    """'sbp' and 'сбп' are payment-rail tokens, never brand identifiers."""
    forbidden = {"sbp", "сбп"}
    violations: list[str] = []
    for row in _load_seed_rows():
        for kind, value, _ in parse_patterns_field(row.get("patterns") or ""):
            if kind == "text" and value.casefold() in forbidden:
                violations.append(f"{row['slug']}: text:{value!r}")
    assert not violations, (
        f"These seed entries have forbidden rail tokens as text patterns: "
        f"{violations}"
    )


# ---------------------------------------------------------------------------
# CSV structural sanity
# ---------------------------------------------------------------------------

def test_seed_csv_has_no_duplicate_slugs() -> None:
    rows = _load_seed_rows()
    slugs = [row["slug"] for row in rows]
    seen: set[str] = set()
    dupes = [s for s in slugs if s in seen or seen.add(s)]  # type: ignore[func-returns-value]
    assert not dupes, f"Duplicate slugs in seed CSV: {dupes}"


def test_seed_csv_all_patterns_have_valid_kind() -> None:
    from app.models.brand import BRAND_PATTERN_KINDS
    valid_kinds = set(BRAND_PATTERN_KINDS) | {"re"}  # "re" is expanded to text+is_regex
    errors: list[str] = []
    for row in _load_seed_rows():
        raw = row.get("patterns") or ""
        for chunk in raw.split("|"):
            chunk = chunk.strip()
            if not chunk:
                continue
            kind = chunk.split(":")[0].strip()
            if kind not in valid_kinds:
                errors.append(f"{row['slug']}: unknown kind {kind!r}")
    assert not errors, f"Invalid pattern kinds in seed CSV: {errors}"
