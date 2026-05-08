"""Tests for the CP→Brand resolver helper that powers Phase C dual-write.

The helper has to behave EXACTLY the same way migration 0067 /
sweep_import_rows_cp_to_brand decided which Brand a Counterparty maps to,
otherwise the FK side and the JSON side drift again — exactly the bug
this whole phase is fixing. So the assertions below mirror the
migration test cases.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.counterparty import Counterparty
from app.models.user import User
from app.services.counterparty_brand_link import (
    resolve_brand_id_for_counterparty,
    resolve_brand_id_for_name,
)


@pytest.fixture
def two_users(db: Session):
    a = User(email="a@x", password_hash="x")
    b = User(email="b@x", password_hash="x")
    db.add_all([a, b])
    db.commit()
    db.refresh(a)
    db.refresh(b)
    return a, b


@pytest.fixture
def global_pyaterochka(db: Session):
    b = Brand(
        slug="pyaterochka", canonical_name="Пятёрочка",
        is_global=True, created_by_user_id=None,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def test_resolve_for_name_creates_private_when_no_match(db, two_users):
    user_a, _ = two_users
    bid = resolve_brand_id_for_name(db, user_id=user_a.id, name="ЛокалКофе")
    db.commit()

    brand = db.query(Brand).filter(Brand.id == bid).one()
    assert brand.canonical_name == "ЛокалКофе"
    assert brand.is_global is False
    assert brand.created_by_user_id == user_a.id
    assert brand.slug.endswith(f"_u{user_a.id}")


def test_resolve_for_name_links_to_global_on_exact_match(
    db, two_users, global_pyaterochka,
):
    user_a, _ = two_users
    bid = resolve_brand_id_for_name(db, user_id=user_a.id, name="Пятёрочка")
    assert bid == global_pyaterochka.id


def test_resolve_for_name_links_to_global_case_insensitive(
    db, two_users, global_pyaterochka,
):
    user_a, _ = two_users
    bid = resolve_brand_id_for_name(db, user_id=user_a.id, name="ПЯТЁРОЧКА")
    assert bid == global_pyaterochka.id


def test_resolve_for_name_user_private_wins_over_global(
    db, two_users, global_pyaterochka,
):
    """User has their own private «Пятёрочка» → should resolve to that,
    not the global. Mirrors migration 0067 priority.
    """
    user_a, _ = two_users
    private = Brand(
        slug=f"pyaterochka_u{user_a.id}",
        canonical_name="Пятёрочка",
        is_global=False,
        created_by_user_id=user_a.id,
    )
    db.add(private)
    db.commit()
    db.refresh(private)

    bid = resolve_brand_id_for_name(db, user_id=user_a.id, name="Пятёрочка")
    assert bid == private.id
    assert bid != global_pyaterochka.id


def test_resolve_cross_user_isolation(db, two_users, global_pyaterochka):
    """User B has no private brand; their CP «Пятёрочка» links to global,
    NOT to user A's private one.
    """
    user_a, user_b = two_users
    db.add(Brand(
        slug=f"pyaterochka_u{user_a.id}", canonical_name="Пятёрочка",
        is_global=False, created_by_user_id=user_a.id,
    ))
    db.commit()

    bid = resolve_brand_id_for_name(db, user_id=user_b.id, name="Пятёрочка")
    assert bid == global_pyaterochka.id


def test_resolve_for_counterparty_returns_brand_id(db, two_users):
    user_a, _ = two_users
    cp = Counterparty(user_id=user_a.id, name="Тестовый Магазин")
    db.add(cp)
    db.commit()
    db.refresh(cp)

    bid = resolve_brand_id_for_counterparty(
        db, user_id=user_a.id, counterparty_id=cp.id,
    )
    db.commit()
    assert bid is not None
    brand = db.query(Brand).filter(Brand.id == bid).one()
    assert brand.canonical_name == "Тестовый Магазин"


def test_resolve_for_counterparty_returns_none_when_missing(db, two_users):
    user_a, _ = two_users
    bid = resolve_brand_id_for_counterparty(
        db, user_id=user_a.id, counterparty_id=99999,
    )
    assert bid is None


def test_resolve_for_counterparty_rejects_other_users_cp(db, two_users):
    """User A's CP cannot be resolved on behalf of user B — silent None
    so the dual-write helper is a no-op rather than crossing user
    boundaries.
    """
    user_a, user_b = two_users
    cp = Counterparty(user_id=user_a.id, name="ABCD")
    db.add(cp)
    db.commit()
    db.refresh(cp)

    bid = resolve_brand_id_for_counterparty(
        db, user_id=user_b.id, counterparty_id=cp.id,
    )
    assert bid is None


def test_resolve_for_name_blank_raises(db, two_users):
    user_a, _ = two_users
    with pytest.raises(ValueError):
        resolve_brand_id_for_name(db, user_id=user_a.id, name="   ")


def test_resolve_for_name_idempotent(db, two_users):
    """Calling twice with the same name must return the same brand_id —
    no duplicate private brand created.
    """
    user_a, _ = two_users
    first = resolve_brand_id_for_name(db, user_id=user_a.id, name="Кофейня")
    db.commit()
    second = resolve_brand_id_for_name(db, user_id=user_a.id, name="Кофейня")
    db.commit()
    assert first == second
    private_count = (
        db.query(Brand)
        .filter(Brand.created_by_user_id == user_a.id)
        .count()
    )
    assert private_count == 1
