"""Phase C step 4 contract: brand confirm writes Brand only.

This file was originally Step 2's dual-write contract suite (CP shadow
created alongside Brand). Step 4 closed the CP write side, so the
original assertions were flipped + paired with positive brand-side
assertions to preserve coverage.

Cases covered:
  • confirm stamps `nd.brand_id` and does NOT touch `nd.counterparty_id`
  • confirm binds the fingerprint on `brand_fingerprints` only —
    `counterparty_fingerprints` stays empty (write side closed)
  • confirm with UserBrandDisplayName surfaces the override label in the
    response, no Counterparty row materialised
  • confirm response carries `brand_display_name` field unchanged
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


def test_confirm_stamps_brand_only_on_row(db, user, global_brand):
    """Phase C step 4: was `test_confirm_stamps_both_brand_and_counterparty_on_row`.
    The CP-side dual-write closed in step 4 — confirm now stamps
    nd.brand_id only and the response's counterparty_id is None.
    """
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
    # Positive: brand stamps present.
    assert nd["brand_id"] == global_brand.id
    assert nd["user_confirmed_brand_id"] == global_brand.id
    assert result["brand_id"] == global_brand.id
    # Negative: nd.counterparty_id no longer stamped, response field is None.
    assert "counterparty_id" not in nd
    assert result["counterparty_id"] is None


def test_confirm_binds_fingerprint_on_brand_store_only(
    db, user, global_brand,
):
    """Phase C step 4: was `test_confirm_binds_fingerprint_on_both_stores`.
    The CP-fp write closed — `brand_fingerprints` is the sole store.
    """
    _, row = _make_active_row(
        db, user_id=user.id, brand_id=global_brand.id,
        fingerprint="fp_dualwrite_002", skeleton="other_skel",
    )
    svc = BrandConfirmService(db)
    svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=global_brand.id,
    )

    # Positive: brand_fingerprints carries the binding.
    bf = (
        db.query(BrandFingerprint)
        .filter(
            BrandFingerprint.user_id == user.id,
            BrandFingerprint.fingerprint == "fp_dualwrite_002",
        )
        .one()
    )
    assert bf.brand_id == global_brand.id

    # Negative: counterparty_fingerprints is no longer written.
    cp_fp = (
        db.query(CounterpartyFingerprint)
        .filter(
            CounterpartyFingerprint.user_id == user.id,
            CounterpartyFingerprint.fingerprint == "fp_dualwrite_002",
        )
        .first()
    )
    assert cp_fp is None


def test_confirm_returns_user_display_name_without_counterparty_shadow(
    db, user, global_brand,
):
    """Phase C step 4: was `test_confirm_uses_user_display_name_for_counterparty_shadow`.
    The Counterparty shadow row is no longer created. The user's
    display label still surfaces via the response's `brand_display_name`
    field; clients that need to render the per-user label read it
    directly instead of going through a CP join.
    """
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

    # Positive: display label flows through the response unchanged.
    assert result["brand_display_name"] == "Пятёрочка у дома"
    # The legacy counterparty_name response field also mirrors the
    # display label so older clients still render the user's label.
    assert result["counterparty_name"] == "Пятёрочка у дома"

    # Negative: no Counterparty row materialised for this user/brand.
    cps = db.query(Counterparty).filter(Counterparty.user_id == user.id).all()
    assert cps == []


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
