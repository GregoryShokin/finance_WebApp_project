"""Tests for BrandResolverService — Brand registry Ph3.

Coverage map (priority pipeline + scoring rules):

  - empty inputs → None
  - text substring match basic
  - text length factor: short pattern stays under threshold
  - longest text pattern wins on tie
  - sbp_merchant_id beats text (kind priority)
  - org_full case-insensitive + whitespace-tolerant
  - alias_exact requires full-string equality
  - inactive patterns excluded
  - global pattern visible to every user
  - private pattern overrides a colliding global pattern
  - other-user private invisible
  - rejections drop pattern below threshold (confidence_factor smoothing)
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.user import User
from app.repositories.brand_repository import BrandRepository
from app.services.brand_resolver_service import (
    BRAND_PROMPT_THRESHOLD,
    BrandResolverService,
)
from app.services.import_normalizer_v2 import ExtractedTokens


@pytest.fixture
def repo(db) -> BrandRepository:
    return BrandRepository(db)


@pytest.fixture
def resolver(db) -> BrandResolverService:
    return BrandResolverService(db)


@pytest.fixture
def other_user(db) -> User:
    u = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_brand_with_pattern(
    repo: BrandRepository,
    db,
    *,
    slug: str,
    canonical_name: str,
    kind: str,
    pattern: str,
    is_global: bool = True,
    scope_user_id: int | None = None,
    category_hint: str | None = None,
    confirms: Decimal = Decimal("0"),
    rejections: Decimal = Decimal("0"),
    is_active: bool = True,
):
    brand = repo.get_brand_by_slug(slug)
    if brand is None:
        brand = repo.create_brand(
            slug=slug,
            canonical_name=canonical_name,
            category_hint=category_hint,
            is_global=is_global if scope_user_id is None else False,
            created_by_user_id=None if (is_global and scope_user_id is None) else scope_user_id,
        )
    bp, _ = repo.upsert_pattern(
        brand_id=brand.id,
        kind=kind,
        pattern=pattern,
        is_global=is_global,
        scope_user_id=scope_user_id,
    )
    bp.confirms = confirms
    bp.rejections = rejections
    bp.is_active = is_active
    db.add(bp)
    db.commit()
    return brand, bp


# ───────────────────────────────────────────────────────────────────
# Degenerate inputs
# ───────────────────────────────────────────────────────────────────


def test_empty_skeleton_and_no_tokens_returns_none(resolver, user):
    result = resolver.resolve(skeleton="", tokens=ExtractedTokens(), user_id=user.id)
    assert result is None


def test_no_patterns_in_db_returns_none(resolver, user):
    result = resolver.resolve(
        skeleton="оплата в pyaterochka",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


# ───────────────────────────────────────────────────────────────────
# text-kind matching
# ───────────────────────────────────────────────────────────────────


def test_text_substring_match_basic(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
        category_hint="Продукты",
    )
    result = resolver.resolve(
        skeleton="оплата в pyaterochka 5024 volgodonsk",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "pyaterochka"
    assert result.canonical_name == "Пятёрочка"
    assert result.category_hint == "Продукты"
    assert result.kind == "text"
    assert result.confidence >= BRAND_PROMPT_THRESHOLD


def test_text_substring_matches_cyrillic(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="пятерочка",
    )
    result = resolver.resolve(
        skeleton="покупка пятерочка магазин",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "pyaterochka"


def test_text_short_pattern_stays_below_threshold(db, repo, resolver, user):
    """A 2-char alias scaled by length_factor (2/8=0.25) → 0.80*0.25 = 0.20.
    Below the 0.65 threshold — resolver must stay silent."""
    _make_brand_with_pattern(
        repo, db,
        slug="wb", canonical_name="Wildberries",
        kind="text", pattern="wb",
    )
    result = resolver.resolve(
        skeleton="оплата wb store moscow",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


def test_text_regex_pattern_matches_split_tokens(db, repo, resolver, user):
    """Regex patterns let one BrandPattern catch split-token descriptions
    like «yandex 5815 plus» that substring matching can't bridge."""
    brand = repo.create_brand(
        slug="yandex_plus", canonical_name="Яндекс Плюс",
        category_hint="Подписки", is_global=True,
    )
    repo.upsert_pattern(
        brand_id=brand.id, kind="text",
        pattern=r"yandex.{0,30}plus",
        is_global=True, is_regex=True,
    )
    db.commit()

    result = resolver.resolve(
        skeleton="оплата в yandex 5815 plus",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "yandex_plus"
    assert result.kind == "text"


def test_text_regex_invalid_pattern_does_not_crash_resolver(db, repo, resolver, user):
    brand = repo.create_brand(
        slug="b", canonical_name="B", is_global=True,
    )
    repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="(unclosed",
        is_global=True, is_regex=True,
    )
    db.commit()

    # Should not raise; resolver simply doesn't return a match for this
    # broken pattern.
    result = resolver.resolve(
        skeleton="some skeleton",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


def test_text_longest_pattern_wins_on_tie(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
    )
    _make_brand_with_pattern(
        repo, db,
        slug="generic-pyat", canonical_name="Pyat?",
        kind="text", pattern="pyat",
    )
    result = resolver.resolve(
        skeleton="pyaterochka 5024 volgodonsk",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "pyaterochka"


# ───────────────────────────────────────────────────────────────────
# kind priority pipeline
# ───────────────────────────────────────────────────────────────────


def test_sbp_merchant_id_wins_over_text(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="vkusno_i_tochka", canonical_name="Вкусно и точка",
        kind="sbp_merchant_id", pattern="26033",
    )
    _make_brand_with_pattern(
        repo, db,
        slug="other-brand", canonical_name="Other",
        kind="text", pattern="vkusno",
    )
    result = resolver.resolve(
        skeleton="26033 vkusno volgodonsk",
        tokens=ExtractedTokens(sbp_merchant_id="26033"),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "vkusno_i_tochka"
    assert result.kind == "sbp_merchant_id"
    assert abs(result.confidence - 0.99) < 1e-6


def test_org_full_case_and_whitespace_insensitive(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="tander", canonical_name="Магнит",
        kind="org_full", pattern="АО Тандер",
    )
    result = resolver.resolve(
        skeleton="some",
        tokens=ExtractedTokens(counterparty_org="ао  тандер"),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "tander"
    assert result.kind == "org_full"


def test_org_full_no_match_when_token_missing(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="tander", canonical_name="Магнит",
        kind="org_full", pattern="АО Тандер",
    )
    result = resolver.resolve(
        skeleton="some",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


def test_alias_exact_requires_full_skeleton_equality(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="wb", canonical_name="Wildberries",
        kind="alias_exact", pattern="wb",
    )

    # exact equality matches
    result = resolver.resolve(skeleton="wb", tokens=ExtractedTokens(), user_id=user.id)
    assert result is not None
    assert result.brand_slug == "wb"

    # extra context kills the match
    result = resolver.resolve(
        skeleton="wb store moscow", tokens=ExtractedTokens(), user_id=user.id,
    )
    assert result is None


# ───────────────────────────────────────────────────────────────────
# is_active + scope filters
# ───────────────────────────────────────────────────────────────────


def test_inactive_pattern_excluded(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
        is_active=False,
    )
    result = resolver.resolve(
        skeleton="pyaterochka 5024",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


def test_global_pattern_visible_to_all_users(db, repo, user, other_user):
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
    )
    r1 = BrandResolverService(db).resolve(
        skeleton="pyaterochka", tokens=ExtractedTokens(), user_id=user.id,
    )
    r2 = BrandResolverService(db).resolve(
        skeleton="pyaterochka", tokens=ExtractedTokens(), user_id=other_user.id,
    )
    assert r1 is not None and r2 is not None
    assert r1.brand_slug == r2.brand_slug == "pyaterochka"


def test_user_private_pattern_overrides_colliding_global(
    db, repo, user,
):
    """User-scope pattern wins over global at the same kind+pattern.

    Uses an 11-char pattern so length_factor=1.0 and both candidates clear
    the threshold — without that, the override mechanic would never get to
    speak (user-scope short-pattern below 0.65 would silently fall through
    to global without us seeing the precedence)."""
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
    )
    private_brand = repo.create_brand(
        slug="my-pyaterochka",
        canonical_name="Моя Пятёрочка у дома",
        is_global=False,
        created_by_user_id=user.id,
    )
    repo.upsert_pattern(
        brand_id=private_brand.id, kind="text", pattern="pyaterochka",
        is_global=False, scope_user_id=user.id,
    )
    db.commit()

    result = BrandResolverService(db).resolve(
        skeleton="pyaterochka 5024 volgodonsk",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is not None
    assert result.brand_slug == "my-pyaterochka"


def test_other_user_private_pattern_invisible(db, repo, user, other_user):
    private_brand = repo.create_brand(
        slug="my-brand",
        canonical_name="My Brand",
        is_global=False,
        created_by_user_id=other_user.id,
    )
    repo.upsert_pattern(
        brand_id=private_brand.id,
        kind="text",
        pattern="my-secret-token",
        is_global=False,
        scope_user_id=other_user.id,
    )
    db.commit()

    result = BrandResolverService(db).resolve(
        skeleton="payment to my-secret-token",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


# ───────────────────────────────────────────────────────────────────
# confidence_factor smoothing
# ───────────────────────────────────────────────────────────────────


def test_heavy_rejections_drop_pattern_below_threshold(db, repo, resolver, user):
    """text base = 0.80; pattern length 11 → factor 1.0; raw score = 0.80.
    confidence_factor = (1+1)/(1+10+1) ≈ 0.167; final = 0.133 → below 0.65."""
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
        confirms=Decimal("1"), rejections=Decimal("10"),
    )
    result = resolver.resolve(
        skeleton="pyaterochka 5024",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is None


def test_high_confirms_keeps_pattern_above_threshold(db, repo, resolver, user):
    _make_brand_with_pattern(
        repo, db,
        slug="pyaterochka", canonical_name="Пятёрочка",
        kind="text", pattern="pyaterochka",
        confirms=Decimal("100"), rejections=Decimal("0"),
    )
    result = resolver.resolve(
        skeleton="pyaterochka 5024",
        tokens=ExtractedTokens(),
        user_id=user.id,
    )
    assert result is not None
    assert result.confidence >= BRAND_PROMPT_THRESHOLD
