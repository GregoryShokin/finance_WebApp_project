"""Unit tests for BrandRepository (Brand registry Ph1).

Coverage:
  - Brand CRUD (create + get_by_id/slug + scope-filtered list)
  - Pattern upsert idempotency (re-running seed must not duplicate)
  - Pattern scope visibility — global visible to all, private only to owner
  - User-private pattern can attach to a global brand (override scenario)
  - Validation guards on scope/global flag inconsistency
"""
from __future__ import annotations

import pytest

from app.models.brand import Brand, BrandPattern
from app.models.user import User
from app.repositories.brand_repository import BrandRepository


@pytest.fixture
def repo(db) -> BrandRepository:
    return BrandRepository(db)


@pytest.fixture
def other_user(db, user) -> User:
    second = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(second)
    db.commit()
    db.refresh(second)
    return second


# ───────────────────────────────────────────────────────────────────
# Brand CRUD
# ───────────────────────────────────────────────────────────────────


def test_create_global_brand_and_lookup_by_slug(db, repo):
    brand = repo.create_brand(
        slug="pyaterochka",
        canonical_name="Пятёрочка",
        category_hint="Продукты",
        is_global=True,
    )
    db.commit()

    assert brand.id is not None
    assert brand.is_global is True
    assert brand.created_by_user_id is None

    assert repo.get_brand_by_slug("pyaterochka").id == brand.id
    assert repo.get_brand(brand.id).slug == "pyaterochka"


def test_create_user_private_brand(db, repo, user):
    brand = repo.create_brand(
        slug="cafe-u-ivanycha",
        canonical_name="Кафе у Иваныча",
        is_global=False,
        created_by_user_id=user.id,
    )
    db.commit()

    assert brand.is_global is False
    assert brand.created_by_user_id == user.id


def test_create_brand_rejects_global_with_owner(repo, user):
    with pytest.raises(ValueError):
        repo.create_brand(
            slug="x",
            canonical_name="X",
            is_global=True,
            created_by_user_id=user.id,
        )


def test_create_brand_rejects_private_without_owner(repo):
    with pytest.raises(ValueError):
        repo.create_brand(
            slug="x", canonical_name="X", is_global=False,
        )


def test_list_brands_for_user_includes_global_and_own_private(
    db, repo, user, other_user,
):
    repo.create_brand(slug="g1", canonical_name="G1", is_global=True)
    repo.create_brand(
        slug="mine", canonical_name="Mine",
        is_global=False, created_by_user_id=user.id,
    )
    repo.create_brand(
        slug="theirs", canonical_name="Theirs",
        is_global=False, created_by_user_id=other_user.id,
    )
    db.commit()

    visible = repo.list_brands_for_user(user_id=user.id)
    slugs = {b.slug for b in visible}

    assert slugs == {"g1", "mine"}


def test_list_global_brands(db, repo, user):
    repo.create_brand(slug="g1", canonical_name="G1", is_global=True)
    repo.create_brand(
        slug="priv", canonical_name="Priv",
        is_global=False, created_by_user_id=user.id,
    )
    db.commit()

    globals_only = repo.list_global_brands()
    assert [b.slug for b in globals_only] == ["g1"]


# ───────────────────────────────────────────────────────────────────
# BrandPattern upsert + scope
# ───────────────────────────────────────────────────────────────────


def test_upsert_pattern_creates_then_no_op_on_repeat(db, repo):
    brand = repo.create_brand(
        slug="vkusno", canonical_name="Вкусно и точка", is_global=True,
    )
    db.commit()

    p1, is_new1 = repo.upsert_pattern(
        brand_id=brand.id, kind="sbp_merchant_id", pattern="26033",
        is_global=True,
    )
    db.commit()
    assert is_new1 is True
    assert p1.confirms == 0
    assert p1.is_active is True

    p2, is_new2 = repo.upsert_pattern(
        brand_id=brand.id, kind="sbp_merchant_id", pattern="26033",
        is_global=True,
    )
    assert is_new2 is False
    assert p2.id == p1.id


def test_upsert_pattern_global_and_private_coexist(db, repo, user):
    brand = repo.create_brand(
        slug="vkusno", canonical_name="Вкусно и точка", is_global=True,
    )
    db.commit()

    g, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="vkusno",
        is_global=True,
    )
    p, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="vkusno",
        is_global=False, scope_user_id=user.id,
    )
    db.commit()

    assert g.id != p.id
    assert g.scope_user_id is None
    assert p.scope_user_id == user.id


def test_upsert_pattern_validates_scope_flag_consistency(repo, user):
    with pytest.raises(ValueError):
        repo.upsert_pattern(
            brand_id=1, kind="text", pattern="x",
            is_global=True, scope_user_id=user.id,
        )
    with pytest.raises(ValueError):
        repo.upsert_pattern(
            brand_id=1, kind="text", pattern="x",
            is_global=False, scope_user_id=None,
        )


def test_upsert_pattern_rejects_unknown_kind(repo):
    with pytest.raises(ValueError):
        repo.upsert_pattern(
            brand_id=1, kind="not_a_kind", pattern="x",
            is_global=True,
        )


def test_list_active_patterns_for_user_scope_filter(
    db, repo, user, other_user,
):
    brand = repo.create_brand(
        slug="b", canonical_name="B", is_global=True,
    )
    db.commit()

    g, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="global-token",
        is_global=True,
    )
    mine, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="my-token",
        is_global=False, scope_user_id=user.id,
    )
    theirs, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="their-token",
        is_global=False, scope_user_id=other_user.id,
    )
    db.commit()

    visible = repo.list_active_patterns_for_user(user_id=user.id)
    pattern_strings = {p.pattern for p in visible}

    assert pattern_strings == {"global-token", "my-token"}


def test_list_active_patterns_excludes_inactive(db, repo, user):
    brand = repo.create_brand(
        slug="b", canonical_name="B", is_global=True,
    )
    db.commit()

    p, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="dead",
        is_global=True,
    )
    p.is_active = False
    db.add(p)
    db.commit()

    visible = repo.list_active_patterns_for_user(user_id=user.id)
    assert visible == []


def test_user_private_pattern_attached_to_global_brand(db, repo, user):
    """Private pattern → global brand: user's local PYAT-MICRO abbreviation
    resolves to canonical Pyaterochka without forking the brand record."""
    brand = repo.create_brand(
        slug="pyaterochka", canonical_name="Пятёрочка", is_global=True,
    )
    db.commit()

    p, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="pyat-micro",
        is_global=False, scope_user_id=user.id,
    )
    db.commit()

    assert p.brand_id == brand.id
    assert p.scope_user_id == user.id

    visible = repo.list_active_patterns_for_user(user_id=user.id)
    assert any(
        v.pattern == "pyat-micro" and v.brand_id == brand.id for v in visible
    )


def test_list_patterns_for_brand(db, repo, user):
    brand = repo.create_brand(
        slug="b", canonical_name="B", is_global=True,
    )
    db.commit()

    repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="t1", is_global=True,
    )
    repo.upsert_pattern(
        brand_id=brand.id, kind="sbp_merchant_id", pattern="12345",
        is_global=True,
    )
    repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="priv",
        is_global=False, scope_user_id=user.id,
    )
    db.commit()

    rows = repo.list_patterns_for_brand(brand_id=brand.id)
    assert len(rows) == 3
