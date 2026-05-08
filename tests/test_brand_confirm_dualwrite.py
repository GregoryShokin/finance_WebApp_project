"""Phase C step 2 contract: brand confirm dual-writes both stores.

The Phase C invariant we're protecting: every brand confirm leaves the
counterparty side AND the brand side in sync. If only one is written,
the next moderator action that reads the other store sees stale data
and the same drift bug Phase C is supposed to fix returns.

Cases covered:
  • confirm stamps `nd.brand_id` AND `nd.counterparty_id`
  • confirm binds the fingerprint to BOTH `brand_fingerprints` and
    `counterparty_fingerprints`
  • confirm with UserBrandDisplayName uses the override label for the
    Counterparty shadow row's name (so legacy lists still show «Пятёрочка
    у дома», not «Пятёрочка»)
  • confirm response carries `brand_display_name` field
"""
from __future__ import annotations

import pytest

from app.models.brand import Brand
from app.models.brand_fingerprint import BrandFingerprint
from app.models.category import Category
from app.models.counterparty import Counterparty
from app.models.counterparty_fingerprint import CounterpartyFingerprint
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.user import User
from app.models.user_brand_display_name import UserBrandDisplayName
from app.services.brand_confirm_service import BrandConfirmService


@pytest.fixture
def user(db):
    u = User(email="dual@x", password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def category(db, user):
    c = Category(user_id=user.id, name="Продукты", type="expense", priority="essentials")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture
def global_brand(db):
    b = Brand(
        slug="pyaterochka", canonical_name="Пятёрочка",
        is_global=True, created_by_user_id=None, category_hint="Продукты",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _make_active_row(db, *, user_id, brand_id, fingerprint, skeleton):
    sess = ImportSession(
        user_id=user_id, status="moderating",
        filename="t.csv", source_type="csv", file_content="",
    )
    db.add(sess)
    db.commit()
    row = ImportRow(
        session_id=sess.id, row_index=0, status="ready",
        normalized_data_json={
            "fingerprint": fingerprint,
            "skeleton": skeleton,
            "brand_id": brand_id,
            "brand_canonical_name": "Пятёрочка",
            "brand_slug": "pyaterochka",
        },
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return sess, row


def test_confirm_stamps_both_brand_and_counterparty_on_row(
    db, user, global_brand,
):
    _, row = _make_active_row(
        db, user_id=user.id, brand_id=global_brand.id,
        fingerprint="fp_pyat_001", skeleton="pyat_skel",
    )
    svc = BrandConfirmService(db)
    result = svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=global_brand.id,
    )

    db.refresh(row)
    nd = row.normalized_data_json
    assert nd["brand_id"] == global_brand.id
    assert nd["user_confirmed_brand_id"] == global_brand.id
    assert nd["counterparty_id"] is not None
    assert result["brand_id"] == global_brand.id
    assert result["counterparty_id"] == nd["counterparty_id"]


def test_confirm_binds_fingerprint_on_both_stores(
    db, user, global_brand,
):
    _, row = _make_active_row(
        db, user_id=user.id, brand_id=global_brand.id,
        fingerprint="fp_dualwrite_002", skeleton="other_skel",
    )
    svc = BrandConfirmService(db)
    svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=global_brand.id,
    )

    bf = (
        db.query(BrandFingerprint)
        .filter(
            BrandFingerprint.user_id == user.id,
            BrandFingerprint.fingerprint == "fp_dualwrite_002",
        )
        .first()
    )
    cp_fp = (
        db.query(CounterpartyFingerprint)
        .filter(
            CounterpartyFingerprint.user_id == user.id,
            CounterpartyFingerprint.fingerprint == "fp_dualwrite_002",
        )
        .first()
    )
    assert bf is not None
    assert bf.brand_id == global_brand.id
    assert cp_fp is not None
    assert cp_fp.counterparty_id is not None


def test_confirm_uses_user_display_name_for_counterparty_shadow(
    db, user, global_brand,
):
    db.add(UserBrandDisplayName(
        user_id=user.id, brand_id=global_brand.id,
        display_name="Пятёрочка у дома",
    ))
    db.commit()

    _, row = _make_active_row(
        db, user_id=user.id, brand_id=global_brand.id,
        fingerprint="fp_dualwrite_003", skeleton="skel3",
    )
    svc = BrandConfirmService(db)
    result = svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=global_brand.id,
    )

    cp = (
        db.query(Counterparty)
        .filter(Counterparty.id == result["counterparty_id"])
        .one()
    )
    assert cp.name == "Пятёрочка у дома"
    assert result["brand_display_name"] == "Пятёрочка у дома"


def test_confirm_falls_back_to_canonical_name_without_override(
    db, user, global_brand,
):
    _, row = _make_active_row(
        db, user_id=user.id, brand_id=global_brand.id,
        fingerprint="fp_dualwrite_004", skeleton="skel4",
    )
    svc = BrandConfirmService(db)
    result = svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=global_brand.id,
    )
    assert result["brand_display_name"] == "Пятёрочка"
