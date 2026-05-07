"""End-to-end pipeline integration of the brand resolver (Brand registry Ph4).

These tests verify that brand_match flows from:
    BrandResolverService.resolve  →  DerivedRow.brand_match
                                  →  NormalizedDataV2.brand_*
                                  →  ImportRow.normalized_data_json.brand_*

They use SQLite in-memory + the real BrandResolverService over real seeded
patterns (no mocking the resolver itself).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.repositories.brand_repository import BrandRepository
from app.repositories.transaction_category_rule_repository import (
    TransactionCategoryRuleRepository,
)
from app.schemas.normalized_row import DerivedRow, ParsedRow
from app.services.brand_resolver_service import BrandMatch, BrandResolverService
from app.services.import_normalization import normalize
from app.services.preview_row_processor import PreviewRowProcessor


# ───────────────────────────────────────────────────────────────────
# normalize() with brand_resolver pass-through
# ───────────────────────────────────────────────────────────────────


def _seed_global_brand(repo: BrandRepository, db, *, slug, canonical, kind, pattern):
    brand = repo.create_brand(
        slug=slug, canonical_name=canonical,
        category_hint="Продукты", is_global=True,
    )
    repo.upsert_pattern(
        brand_id=brand.id, kind=kind, pattern=pattern, is_global=True,
    )
    db.commit()
    return brand


def test_normalize_passes_brand_match_into_derived(db, user):
    repo = BrandRepository(db)
    brand = _seed_global_brand(
        repo, db,
        slug="pyaterochka", canonical="Пятёрочка",
        kind="text", pattern="pyaterochka",
    )

    raw_row = {
        "Дата": "15.01.2026",
        "Описание": "Покупка PYATEROCHKA 5024 Volgodonsk",
        "Сумма": "-450.00",
    }
    parsed, derived = normalize(
        raw_row=raw_row,
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        bank="tbank",
        account_id=1,
        brand_resolver=BrandResolverService(db),
        user_id=user.id,
    )

    assert derived.brand_match is not None
    assert derived.brand_match.brand_slug == "pyaterochka"
    assert derived.brand_match.canonical_name == "Пятёрочка"
    assert derived.brand_match.brand_id == brand.id
    assert derived.brand_match.kind == "text"


def test_normalize_brand_match_none_when_no_seed_matches(db, user):
    """Empty registry — derive should still succeed, brand_match=None."""
    raw_row = {
        "Дата": "15.01.2026",
        "Описание": "Кофе на станции",
        "Сумма": "-150.00",
    }
    _, derived = normalize(
        raw_row=raw_row,
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        bank="tbank",
        account_id=1,
        brand_resolver=BrandResolverService(db),
        user_id=user.id,
    )
    assert derived.brand_match is None


def test_normalize_without_resolver_leaves_brand_match_none(db, user):
    """Legacy callers that don't pass a resolver must still work."""
    raw_row = {
        "Дата": "15.01.2026",
        "Описание": "Покупка PYATEROCHKA",
        "Сумма": "-100.00",
    }
    _, derived = normalize(
        raw_row=raw_row,
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        bank="tbank",
        account_id=1,
        # brand_resolver omitted intentionally
    )
    assert derived.brand_match is None


def test_normalize_swallows_resolver_exception(db, user, caplog):
    """A throwing resolver must NOT break the import pipeline. Spec §11.1
    swallow strategy — log warning, brand_match stays None, import proceeds."""
    bad_resolver = MagicMock()
    bad_resolver.resolve.side_effect = RuntimeError("boom")

    raw_row = {
        "Дата": "15.01.2026", "Описание": "x", "Сумма": "-100.00",
    }
    _, derived = normalize(
        raw_row=raw_row,
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        bank="tbank",
        account_id=1,
        brand_resolver=bad_resolver,
        user_id=user.id,
    )
    assert derived.brand_match is None
    bad_resolver.resolve.assert_called_once()


# ───────────────────────────────────────────────────────────────────
# End-to-end via PreviewRowProcessor
# ───────────────────────────────────────────────────────────────────


def test_preview_row_processor_persists_brand_fields_into_normalized_data(
    db, user,
):
    repo = BrandRepository(db)
    brand = _seed_global_brand(
        repo, db,
        slug="vkusno_i_tochka", canonical="Вкусно и точка",
        kind="text", pattern="vkusno_i_tochka",
    )

    enrichment = MagicMock()
    enrichment.enrich_import_row.return_value = {
        "suggested_account_id": None,
        "suggested_target_account_id": None,
        "suggested_category_id": None,
        "suggested_operation_type": "regular",
        "suggested_type": "expense",
        "normalized_description": "vkusno_i_tochka",
        "assignment_confidence": 0.0,
        "assignment_reasons": [],
        "review_reasons": [],
        "needs_manual_review": False,
    }

    processor = PreviewRowProcessor(
        db,
        category_rule_repo=TransactionCategoryRuleRepository(db),
        enrichment=enrichment,
        find_duplicate_fn=lambda **kw: False,
        alias_service=None,
        brand_resolver=BrandResolverService(db),
    )

    processed = processor.process(
        raw_row={
            "Дата": "15.01.2026",
            "Описание": "Оплата vkusno_i_tochka Москва",
            "Сумма": "-450.00",
        },
        row_index=1,
        user_id=user.id,
        session_account_id=1,
        bank_code="tbank",
        bank_for_normalize="tbank",
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        skip_duplicates=False,
        accounts_cache=[],
        categories_cache=[],
        history_sample_cache=[],
    )

    nd = processed.normalized
    assert nd["brand_id"] == brand.id
    assert nd["brand_slug"] == "vkusno_i_tochka"
    assert nd["brand_canonical_name"] == "Вкусно и точка"
    assert nd["brand_category_hint"] == "Продукты"
    assert nd["brand_kind"] == "text"
    assert nd["brand_confidence"] >= 0.65


def test_preview_row_processor_omits_brand_when_no_match(db, user):
    enrichment = MagicMock()
    enrichment.enrich_import_row.return_value = {
        "suggested_account_id": None,
        "suggested_target_account_id": None,
        "suggested_category_id": None,
        "suggested_operation_type": "regular",
        "suggested_type": "expense",
        "normalized_description": "x",
        "assignment_confidence": 0.0,
        "assignment_reasons": [],
        "review_reasons": [],
        "needs_manual_review": False,
    }

    processor = PreviewRowProcessor(
        db,
        category_rule_repo=TransactionCategoryRuleRepository(db),
        enrichment=enrichment,
        find_duplicate_fn=lambda **kw: False,
        alias_service=None,
        brand_resolver=BrandResolverService(db),
    )

    processed = processor.process(
        raw_row={
            "Дата": "15.01.2026",
            "Описание": "Какой-то неизвестный мерчант",
            "Сумма": "-100.00",
        },
        row_index=1,
        user_id=user.id,
        session_account_id=1,
        bank_code="tbank",
        bank_for_normalize="tbank",
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        skip_duplicates=False,
        accounts_cache=[],
        categories_cache=[],
        history_sample_cache=[],
    )

    assert processed.normalized.get("brand_id") is None
    assert processed.normalized.get("brand_slug") is None


def test_preview_row_processor_works_without_resolver(db, user):
    """Backward-compat: PreviewRowProcessor accepts brand_resolver=None
    (or omitted) and produces normalized data with brand_* = None."""
    enrichment = MagicMock()
    enrichment.enrich_import_row.return_value = {
        "suggested_account_id": None,
        "suggested_target_account_id": None,
        "suggested_category_id": None,
        "suggested_operation_type": "regular",
        "suggested_type": "expense",
        "normalized_description": "x",
        "assignment_confidence": 0.0,
        "assignment_reasons": [],
        "review_reasons": [],
        "needs_manual_review": False,
    }

    processor = PreviewRowProcessor(
        db,
        category_rule_repo=TransactionCategoryRuleRepository(db),
        enrichment=enrichment,
        find_duplicate_fn=lambda **kw: False,
        alias_service=None,
        # brand_resolver omitted
    )

    processed = processor.process(
        raw_row={
            "Дата": "15.01.2026", "Описание": "x", "Сумма": "-100.00",
        },
        row_index=1,
        user_id=user.id,
        session_account_id=1,
        bank_code="tbank",
        bank_for_normalize="tbank",
        field_mapping={"date": "Дата", "description": "Описание", "amount": "Сумма"},
        date_format="%d.%m.%Y",
        default_currency="RUB",
        skip_duplicates=False,
        accounts_cache=[],
        categories_cache=[],
        history_sample_cache=[],
    )

    assert processed.status in ("ready", "warning")
    assert processed.normalized.get("brand_id") is None
