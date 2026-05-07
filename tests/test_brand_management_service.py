"""Unit tests for BrandManagementService — Brand registry Ph8b.

Coverage:
  - create_private_brand: slug stable + unique across users
  - _slugify: cyrillic + punctuation + collisions
  - add_pattern_to_brand: own private ✓, global brand override ✓, foreign private ✗
  - list_brands_for_picker: scope filter + q substring + limit
  - get_with_patterns: visibility (private own / global), filters foreign user-scope patterns
  - suggest_from_row: sbp_merchant_id wins over text; text fallback; None on empty
  - list_unresolved_groups: threshold (≥3), excludes transfers / user_decision / committed
"""
from __future__ import annotations

import pytest

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.user import User
from app.repositories.brand_repository import BrandRepository
from app.services.brand_management_service import (
    BrandManagementError,
    BrandManagementService,
    _slugify,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(db) -> BrandRepository:
    return BrandRepository(db)


@pytest.fixture
def service(db) -> BrandManagementService:
    return BrandManagementService(db)


@pytest.fixture
def other_user(db) -> User:
    u = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _mk_session(db, user_id: int, *, status: str = "preview_ready") -> ImportSession:
    s = ImportSession(
        user_id=user_id,
        filename="t.csv",
        source_type="csv",
        status=status,
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _mk_row(
    db,
    session_id: int,
    *,
    row_index: int,
    description: str,
    skeleton: str,
    tokens: dict | None = None,
    operation_type: str = "regular",
    brand_id: int | None = None,
    user_confirmed_brand_id: int | None = None,
    user_rejected_brand_id: int | None = None,
) -> ImportRow:
    nd = {
        "skeleton": skeleton,
        "tokens": tokens or {},
        "operation_type": operation_type,
        "brand_id": brand_id,
        "original_description": description,
    }
    if user_confirmed_brand_id is not None:
        nd["user_confirmed_brand_id"] = user_confirmed_brand_id
    if user_rejected_brand_id is not None:
        nd["user_rejected_brand_id"] = user_rejected_brand_id
    r = ImportRow(
        session_id=session_id,
        row_index=row_index,
        raw_data_json={},
        normalized_data_json=nd,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ──────────────────────────────────────────────────────────────────────
# _slugify
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name,expected", [
    ("Nippon Coffee", "nippon_coffee"),
    ("nippon coffee", "nippon_coffee"),
    ("Nippon-Coffee", "nippon_coffee"),
    ("Кофейня У Дома", "kofeynya_u_doma"),
    ("Кафе «У Иваныча»", "kafe_u_ivanycha"),
    ("ВкусВилл", "vkusvill"),
    ("KFC", "kfc"),
    ("Ёжик 🦔 в тумане", "ezhik_v_tumane"),
    # Empty / fully-non-alpha → empty (caller substitutes "brand")
    ("", ""),
    ("   ", ""),
    ("...---", ""),
])
def test_slugify(name: str, expected: str) -> None:
    assert _slugify(name) == expected


# ──────────────────────────────────────────────────────────────────────
# create_private_brand
# ──────────────────────────────────────────────────────────────────────


def test_create_private_brand_happy_path(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id,
        canonical_name="Nippon Coffee",
        category_hint="Кафе и рестораны",
    )
    db.commit()
    assert brand.id is not None
    assert brand.is_global is False
    assert brand.created_by_user_id == user.id
    assert brand.slug.startswith("nippon_coffee")
    assert f"_u{user.id}" in brand.slug
    assert brand.canonical_name == "Nippon Coffee"
    assert brand.category_hint == "Кафе и рестораны"


def test_create_private_brand_slug_namespaced_per_user(service, db, user, other_user):
    """Two users can both create «Nippon» — slugs are per-user-namespaced."""
    b1 = service.create_private_brand(
        user_id=user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    b2 = service.create_private_brand(
        user_id=other_user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    assert b1.slug != b2.slug
    assert b1.slug == f"nippon_u{user.id}"
    assert b2.slug == f"nippon_u{other_user.id}"


def test_create_private_brand_appends_counter_on_collision(service, db, user):
    """Same user creating «Nippon» twice → slug gets _2 suffix."""
    service.create_private_brand(
        user_id=user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    b2 = service.create_private_brand(
        user_id=user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    assert b2.slug.endswith("_2")


def test_create_private_brand_rejects_blank_name(service, user):
    with pytest.raises(BrandManagementError):
        service.create_private_brand(
            user_id=user.id, canonical_name="   ", category_hint=None,
        )


def test_create_private_brand_strips_blank_category_hint(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="X", category_hint="   ",
    )
    db.commit()
    assert brand.category_hint is None


# ──────────────────────────────────────────────────────────────────────
# add_pattern_to_brand
# ──────────────────────────────────────────────────────────────────────


def test_add_pattern_to_own_private_brand(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    bp, is_new = service.add_pattern_to_brand(
        user_id=user.id, brand_id=brand.id,
        kind="text", pattern="nippon",
    )
    db.commit()
    assert is_new is True
    assert bp.is_global is False
    assert bp.scope_user_id == user.id
    assert bp.kind == "text"
    assert bp.pattern == "nippon"


def test_add_pattern_to_global_brand_creates_private_override(service, repo, db, user):
    """User can attach a private pattern to a maintainer-curated global brand."""
    global_brand = repo.create_brand(
        slug="pyaterochka", canonical_name="Пятёрочка",
        is_global=True,
    )
    db.commit()
    bp, _ = service.add_pattern_to_brand(
        user_id=user.id, brand_id=global_brand.id,
        kind="text", pattern="pyat-tt-5024",
    )
    db.commit()
    # Stored as private override even though brand is global
    assert bp.is_global is False
    assert bp.scope_user_id == user.id


def test_add_pattern_to_foreign_private_brand_rejected(service, db, user, other_user):
    other_brand = service.create_private_brand(
        user_id=other_user.id, canonical_name="Other", category_hint=None,
    )
    db.commit()
    with pytest.raises(BrandManagementError):
        service.add_pattern_to_brand(
            user_id=user.id, brand_id=other_brand.id,
            kind="text", pattern="x",
        )


def test_add_pattern_idempotent(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    bp1, is_new_1 = service.add_pattern_to_brand(
        user_id=user.id, brand_id=brand.id, kind="text", pattern="nippon",
    )
    db.commit()
    bp2, is_new_2 = service.add_pattern_to_brand(
        user_id=user.id, brand_id=brand.id, kind="text", pattern="nippon",
    )
    db.commit()
    assert is_new_1 is True
    assert is_new_2 is False
    assert bp1.id == bp2.id


def test_add_pattern_rejects_blank_pattern(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="X", category_hint=None,
    )
    db.commit()
    with pytest.raises(BrandManagementError):
        service.add_pattern_to_brand(
            user_id=user.id, brand_id=brand.id, kind="text", pattern="   ",
        )


def test_add_pattern_to_unknown_brand_rejected(service, user):
    with pytest.raises(BrandManagementError):
        service.add_pattern_to_brand(
            user_id=user.id, brand_id=99999, kind="text", pattern="x",
        )


# ──────────────────────────────────────────────────────────────────────
# list_brands_for_picker
# ──────────────────────────────────────────────────────────────────────


def test_list_brands_for_picker_combines_scopes(service, repo, db, user):
    repo.create_brand(slug="pyaterochka", canonical_name="Пятёрочка", is_global=True)
    service.create_private_brand(
        user_id=user.id, canonical_name="Nippon", category_hint=None,
    )
    db.commit()
    out = service.list_brands_for_picker(user_id=user.id)
    slugs = {b.slug for b in out}
    assert "pyaterochka" in slugs
    assert any(s.startswith("nippon_u") for s in slugs)


def test_list_brands_for_picker_scope_private_only(service, repo, db, user):
    repo.create_brand(slug="pyaterochka", canonical_name="Пятёрочка", is_global=True)
    service.create_private_brand(user_id=user.id, canonical_name="Nippon", category_hint=None)
    db.commit()
    out = service.list_brands_for_picker(user_id=user.id, scope="private")
    assert all(not b.is_global for b in out)
    assert len(out) == 1


def test_list_brands_for_picker_q_filter(service, repo, db, user):
    repo.create_brand(slug="pyaterochka", canonical_name="Пятёрочка", is_global=True)
    repo.create_brand(slug="magnit", canonical_name="Магнит", is_global=True)
    db.commit()
    out = service.list_brands_for_picker(user_id=user.id, q="пятёр")
    assert len(out) == 1
    assert out[0].slug == "pyaterochka"


def test_list_brands_for_picker_excludes_other_users_private(
    service, db, user, other_user,
):
    service.create_private_brand(
        user_id=other_user.id, canonical_name="OtherSecret", category_hint=None,
    )
    db.commit()
    out = service.list_brands_for_picker(user_id=user.id)
    assert all("othersecret" not in b.slug.lower() for b in out)


# ──────────────────────────────────────────────────────────────────────
# get_with_patterns
# ──────────────────────────────────────────────────────────────────────


def test_get_with_patterns_filters_foreign_overrides(service, repo, db, user, other_user):
    """Other users' private patterns on a global brand must not leak."""
    global_brand = repo.create_brand(
        slug="pyaterochka", canonical_name="Пятёрочка", is_global=True,
    )
    # Maintainer pattern (visible)
    repo.upsert_pattern(
        brand_id=global_brand.id, kind="text", pattern="pyaterochka", is_global=True,
    )
    # Our private override (visible)
    service.add_pattern_to_brand(
        user_id=user.id, brand_id=global_brand.id,
        kind="text", pattern="my-pyat",
    )
    # Other user's private override (must NOT be visible)
    service.add_pattern_to_brand(
        user_id=other_user.id, brand_id=global_brand.id,
        kind="text", pattern="other-secret",
    )
    db.commit()

    _, patterns = service.get_with_patterns(user_id=user.id, brand_id=global_brand.id)
    pattern_values = {p.pattern for p in patterns}
    assert "pyaterochka" in pattern_values
    assert "my-pyat" in pattern_values
    assert "other-secret" not in pattern_values


def test_get_with_patterns_blocks_foreign_private_brand(service, db, user, other_user):
    other = service.create_private_brand(
        user_id=other_user.id, canonical_name="Other", category_hint=None,
    )
    db.commit()
    with pytest.raises(BrandManagementError):
        service.get_with_patterns(user_id=user.id, brand_id=other.id)


# ──────────────────────────────────────────────────────────────────────
# suggest_from_row
# ──────────────────────────────────────────────────────────────────────


def test_suggest_from_row_text_path(service, db, user):
    s = _mk_session(db, user.id)
    row = _mk_row(
        db, s.id,
        row_index=0,
        description="Оплата в NIPPON Volgodonsk RUS",
        skeleton="оплата в nippon",
        tokens={},
    )
    canonical, kind, value = service.suggest_from_row(
        user_id=user.id, row_id=row.id,
    )
    assert canonical == "Nippon"
    assert kind == "text"
    assert value == "nippon"


def test_suggest_from_row_sbp_merchant_id_wins_over_text(service, db, user):
    s = _mk_session(db, user.id)
    row = _mk_row(
        db, s.id,
        row_index=0,
        description="Оплата в QSR 26033_P_QR 1232",
        skeleton="оплата в 26033 <SBP_PAYMENT>",
        tokens={"sbp_merchant_id": "26033", "card_last4": "1232"},
    )
    canonical, kind, value = service.suggest_from_row(
        user_id=user.id, row_id=row.id,
    )
    # sbp_merchant_id is more precise than the text candidate (which would
    # be None here anyway because skeleton tokens are all filler/digits).
    assert kind == "sbp_merchant_id"
    assert value == "26033"


def test_suggest_from_row_returns_none_when_skeleton_empty(service, db, user):
    s = _mk_session(db, user.id)
    row = _mk_row(
        db, s.id, row_index=0,
        description="Перевод между своими",
        skeleton="",
        tokens={},
    )
    canonical, kind, value = service.suggest_from_row(
        user_id=user.id, row_id=row.id,
    )
    assert (canonical, kind, value) == (None, None, None)


def test_suggest_from_row_blocks_foreign_user(service, db, user, other_user):
    s = _mk_session(db, other_user.id)
    row = _mk_row(
        db, s.id, row_index=0,
        description="Оплата в NIPPON",
        skeleton="оплата в nippon", tokens={},
    )
    out = service.suggest_from_row(user_id=user.id, row_id=row.id)
    assert out == (None, None, None)


# ──────────────────────────────────────────────────────────────────────
# list_unresolved_groups
# ──────────────────────────────────────────────────────────────────────


def test_unresolved_groups_threshold(service, db, user):
    """≥3 rows of same candidate become a suggestion; below threshold is silent."""
    s = _mk_session(db, user.id)
    # 4 nippon rows → suggestion
    for i in range(4):
        _mk_row(
            db, s.id, row_index=i,
            description=f"Оплата в NIPPON #{i}",
            skeleton="оплата в nippon", tokens={},
        )
    # 2 zorbas rows → below threshold
    for i in range(2):
        _mk_row(
            db, s.id, row_index=10 + i,
            description=f"Оплата в ZORBAS #{i}",
            skeleton="оплата в zorbas", tokens={},
        )

    out = service.list_unresolved_groups(user_id=user.id)
    candidates = [g.candidate for g in out]
    assert "nippon" in candidates
    assert "zorbas" not in candidates


def test_unresolved_groups_excludes_transfers(service, db, user):
    s = _mk_session(db, user.id)
    for i in range(5):
        _mk_row(
            db, s.id, row_index=i,
            description="Внешний перевод",
            skeleton="внешний перевод",
            tokens={},
            operation_type="transfer",
        )
    out = service.list_unresolved_groups(user_id=user.id)
    assert out == []


def test_unresolved_groups_excludes_already_branded(service, db, user):
    s = _mk_session(db, user.id)
    for i in range(5):
        _mk_row(
            db, s.id, row_index=i,
            description=f"Оплата в NIPPON #{i}",
            skeleton="оплата в nippon", tokens={},
            brand_id=42,  # already resolved
        )
    out = service.list_unresolved_groups(user_id=user.id)
    assert out == []


def test_unresolved_groups_excludes_user_decisions(service, db, user):
    s = _mk_session(db, user.id)
    for i in range(5):
        _mk_row(
            db, s.id, row_index=i,
            description=f"Оплата в NIPPON #{i}",
            skeleton="оплата в nippon", tokens={},
            user_rejected_brand_id=99,
        )
    out = service.list_unresolved_groups(user_id=user.id)
    assert out == []


def test_unresolved_groups_excludes_committed_sessions(service, db, user):
    s = _mk_session(db, user.id, status="committed")
    for i in range(5):
        _mk_row(
            db, s.id, row_index=i,
            description=f"Оплата в NIPPON #{i}",
            skeleton="оплата в nippon", tokens={},
        )
    out = service.list_unresolved_groups(user_id=user.id)
    assert out == []


def test_unresolved_groups_isolates_users(service, db, user, other_user):
    s_us = _mk_session(db, user.id)
    s_them = _mk_session(db, other_user.id)
    for i in range(5):
        _mk_row(
            db, s_us.id, row_index=i,
            description="Оплата в NIPPON",
            skeleton="оплата в nippon", tokens={},
        )
        _mk_row(
            db, s_them.id, row_index=i,
            description="Оплата в OTHERBRAND",
            skeleton="оплата в otherbrand", tokens={},
        )

    ours = service.list_unresolved_groups(user_id=user.id)
    theirs = service.list_unresolved_groups(user_id=other_user.id)
    assert {g.candidate for g in ours} == {"nippon"}
    assert {g.candidate for g in theirs} == {"otherbrand"}


def test_apply_brand_to_session_rejects_foreign_brand(service, db, user, other_user):
    other = service.create_private_brand(
        user_id=other_user.id, canonical_name="Other", category_hint=None,
    )
    db.commit()
    s = _mk_session(db, user.id)
    with pytest.raises(BrandManagementError):
        service.apply_brand_to_session(
            user_id=user.id, brand_id=other.id, session_id=s.id,
        )


def test_apply_brand_to_session_rejects_unknown_brand(service, db, user):
    s = _mk_session(db, user.id)
    with pytest.raises(BrandManagementError):
        service.apply_brand_to_session(
            user_id=user.id, brand_id=99999, session_id=s.id,
        )


def test_apply_brand_to_session_rejects_unknown_session(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="X", category_hint=None,
    )
    db.commit()
    with pytest.raises(BrandManagementError):
        service.apply_brand_to_session(
            user_id=user.id, brand_id=brand.id, session_id=99999,
        )


def test_apply_brand_to_session_rejects_committed_session(service, db, user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="X", category_hint=None,
    )
    s = _mk_session(db, user.id, status="committed")
    db.commit()
    with pytest.raises(BrandManagementError):
        service.apply_brand_to_session(
            user_id=user.id, brand_id=brand.id, session_id=s.id,
        )


def test_apply_brand_to_session_rejects_foreign_session(service, db, user, other_user):
    brand = service.create_private_brand(
        user_id=user.id, canonical_name="X", category_hint=None,
    )
    s_other = _mk_session(db, other_user.id)
    db.commit()
    with pytest.raises(BrandManagementError):
        service.apply_brand_to_session(
            user_id=user.id, brand_id=brand.id, session_id=s_other.id,
        )


def test_unresolved_groups_sample_payload(service, db, user):
    s = _mk_session(db, user.id)
    for i in range(4):
        _mk_row(
            db, s.id, row_index=i,
            description=f"Оплата в NIPPON variant {i}",
            skeleton="оплата в nippon", tokens={},
        )
    out = service.list_unresolved_groups(user_id=user.id)
    assert len(out) == 1
    g = out[0]
    assert g.candidate == "nippon"
    assert g.row_count == 4
    assert len(g.sample_descriptions) == 3
    assert len(g.sample_row_ids) == 3
