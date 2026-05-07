"""Tests for scripts.seed_brand_registry — Brand registry Ph2.

Covers idempotency (re-running yields no duplicates), update flow (CSV
change → existing brand row mutates), pattern parsing edge cases, and
malformed-input handling.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.repositories.brand_repository import BrandRepository
from scripts.seed_brand_registry import (
    SeedReport,
    parse_patterns_field,
    seed_from_csv,
)


def _write_csv(tmp_path: Path, body: str) -> Path:
    csv_path = tmp_path / "brands.csv"
    csv_path.write_text(
        "slug,canonical_name,category_hint,patterns\n" + body,
        encoding="utf-8",
    )
    return csv_path


# ───────────────────────────────────────────────────────────────────
# parse_patterns_field
# ───────────────────────────────────────────────────────────────────


def test_parse_patterns_field_empty_returns_empty_list():
    assert parse_patterns_field("") == []
    assert parse_patterns_field("   ") == []


def test_parse_patterns_field_simple():
    items = parse_patterns_field("text:foo|sbp_merchant_id:26033")
    assert items == [
        ("text", "foo", False),
        ("sbp_merchant_id", "26033", False),
    ]


def test_parse_patterns_field_strips_whitespace():
    items = parse_patterns_field(" text:foo |  text:bar ")
    assert items == [("text", "foo", False), ("text", "bar", False)]


def test_parse_patterns_field_regex_prefix():
    items = parse_patterns_field("re:yandex.{0,30}plus|text:literal")
    assert items == [
        ("text", "yandex.{0,30}plus", True),
        ("text", "literal", False),
    ]


def test_parse_patterns_field_rejects_missing_colon():
    with pytest.raises(ValueError, match="missing ':' separator"):
        parse_patterns_field("text:foo|just_a_word")


def test_parse_patterns_field_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported pattern kind"):
        parse_patterns_field("text:foo|nope:bar")


def test_parse_patterns_field_rejects_empty_value():
    with pytest.raises(ValueError, match="empty kind/value"):
        parse_patterns_field("text:")


# ───────────────────────────────────────────────────────────────────
# seed_from_csv: end-to-end
# ───────────────────────────────────────────────────────────────────


def test_seed_creates_brands_and_patterns(db, tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka|text:пятерочка\n"
        "magnit,Магнит,Продукты,text:magnit\n",
    )

    report = seed_from_csv(db, csv_path)
    db.commit()

    assert report.brands_created == 2
    assert report.brands_updated == 0
    assert report.patterns_created == 3
    assert report.errors == []

    repo = BrandRepository(db)
    pyat = repo.get_brand_by_slug("pyaterochka")
    assert pyat is not None
    assert pyat.is_global is True
    assert pyat.created_by_user_id is None
    assert pyat.canonical_name == "Пятёрочка"
    assert pyat.category_hint == "Продукты"

    patterns = repo.list_patterns_for_brand(brand_id=pyat.id)
    assert {p.pattern for p in patterns} == {"pyaterochka", "пятерочка"}
    assert all(p.is_global is True for p in patterns)


def test_seed_idempotent_second_run_no_duplicates(db, tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka\n",
    )

    seed_from_csv(db, csv_path)
    db.commit()

    second = seed_from_csv(db, csv_path)
    db.commit()

    assert second.brands_created == 0
    assert second.brands_updated == 0
    assert second.brands_unchanged == 1
    assert second.patterns_created == 0
    assert second.patterns_unchanged == 1


def test_seed_updates_canonical_name_when_csv_changes(db, tmp_path):
    csv_v1 = _write_csv(
        tmp_path,
        "pyaterochka,Пятерочка,Продукты,text:pyaterochka\n",
    )
    seed_from_csv(db, csv_v1)
    db.commit()

    # Rewrite CSV with refined name (with ё) and category change
    csv_v2 = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Магазины у дома,text:pyaterochka\n",
    )
    report = seed_from_csv(db, csv_v2)
    db.commit()

    assert report.brands_created == 0
    assert report.brands_updated == 1
    assert report.patterns_created == 0

    repo = BrandRepository(db)
    pyat = repo.get_brand_by_slug("pyaterochka")
    assert pyat.canonical_name == "Пятёрочка"
    assert pyat.category_hint == "Магазины у дома"


def test_seed_appends_new_patterns_to_existing_brand(db, tmp_path):
    csv_v1 = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka\n",
    )
    seed_from_csv(db, csv_v1)
    db.commit()

    # Add another pattern variant
    csv_v2 = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka|text:пятёрочка\n",
    )
    report = seed_from_csv(db, csv_v2)
    db.commit()

    assert report.patterns_created == 1
    assert report.patterns_unchanged == 1

    repo = BrandRepository(db)
    pyat = repo.get_brand_by_slug("pyaterochka")
    assert len(repo.list_patterns_for_brand(brand_id=pyat.id)) == 2


def test_seed_does_not_remove_orphaned_patterns(db, tmp_path):
    csv_v1 = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka|text:старый_паттерн\n",
    )
    seed_from_csv(db, csv_v1)
    db.commit()

    # Drop one of the patterns from the CSV
    csv_v2 = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka\n",
    )
    seed_from_csv(db, csv_v2)
    db.commit()

    repo = BrandRepository(db)
    pyat = repo.get_brand_by_slug("pyaterochka")
    patterns = {p.pattern for p in repo.list_patterns_for_brand(brand_id=pyat.id)}
    assert patterns == {"pyaterochka", "старый_паттерн"}


def test_seed_does_not_touch_user_private_patterns(db, tmp_path, user):
    csv_path = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka\n",
    )
    seed_from_csv(db, csv_path)
    db.commit()

    repo = BrandRepository(db)
    pyat = repo.get_brand_by_slug("pyaterochka")
    private_pattern, _ = repo.upsert_pattern(
        brand_id=pyat.id,
        kind="text",
        pattern="pyat-micro",
        is_global=False,
        scope_user_id=user.id,
    )
    db.commit()

    # Re-running seed must not touch the private pattern
    seed_from_csv(db, csv_path)
    db.commit()

    db.refresh(private_pattern)
    assert private_pattern.is_active is True
    assert private_pattern.scope_user_id == user.id


def test_seed_reports_errors_for_malformed_rows(db, tmp_path):
    csv_path = _write_csv(
        tmp_path,
        "pyaterochka,Пятёрочка,Продукты,text:pyaterochka\n"
        ",NoSlug,Продукты,text:foo\n"
        "dup,Dup,Продукты,text:bar\n"
        "dup,Dup2,Продукты,text:baz\n"
        "bad_kind,X,Продукты,text:foo|wrong:bar\n",
    )
    report = seed_from_csv(db, csv_path)
    db.commit()

    assert report.brands_created == 2  # pyaterochka + first 'dup'
    assert len(report.errors) == 3


def test_seed_rejects_csv_with_missing_columns(db, tmp_path):
    csv_path = tmp_path / "broken.csv"
    csv_path.write_text("slug,canonical_name\nfoo,Foo\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        seed_from_csv(db, csv_path)


# ───────────────────────────────────────────────────────────────────
# Default seed file shipped with the repo — sanity smoke
# ───────────────────────────────────────────────────────────────────


def test_default_seed_csv_loads_cleanly(db):
    """The committed data/brands_seed_v1.csv must parse and apply
    without errors. This catches typos and bad pattern syntax in the
    curated registry before deploy."""
    csv_path = Path(__file__).resolve().parent.parent / "data" / "brands_seed_v1.csv"
    assert csv_path.exists(), f"seed CSV not found at {csv_path}"

    report = seed_from_csv(db, csv_path)
    db.commit()

    assert report.errors == [], f"seed errors: {report.errors}"
    assert report.brands_created >= 15, (
        f"expected at least 15 seed brands, got {report.brands_created}"
    )
    assert report.patterns_created > report.brands_created, (
        "every brand should ship multiple patterns"
    )

    # Spot-check a known-stable entry
    repo = BrandRepository(db)
    vkusno = repo.get_brand_by_slug("vkusno_i_tochka")
    assert vkusno is not None
    assert vkusno.canonical_name == "Вкусно и точка"
    assert vkusno.category_hint == "Кафе и рестораны"
