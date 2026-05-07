"""Tests for BrandPatternStrengthService — Brand registry Ph6."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.repositories.brand_repository import BrandRepository
from app.services.brand_pattern_strength_service import (
    DEACTIVATE_REJECTIONS,
    BrandPatternNotFound,
    BrandPatternStrengthService,
)


@pytest.fixture
def pattern(db):
    repo = BrandRepository(db)
    brand = repo.create_brand(
        slug="pyaterochka", canonical_name="Пятёрочка", is_global=True,
    )
    bp, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="pyaterochka", is_global=True,
    )
    db.commit()
    return bp


# ───────────────────────────────────────────────────────────────────
# on_confirmed
# ───────────────────────────────────────────────────────────────────


def test_on_confirmed_increments_confirms(db, pattern):
    svc = BrandPatternStrengthService(db)
    transition = svc.on_confirmed(pattern.id)
    db.commit()

    assert transition.event == "confirmed"
    assert transition.confirms_before == Decimal("0")
    assert transition.confirms_after == Decimal("1")
    assert transition.is_active_after is True


def test_on_confirmed_accepts_custom_delta(db, pattern):
    svc = BrandPatternStrengthService(db)
    transition = svc.on_confirmed(pattern.id, delta=Decimal("5"))
    db.commit()
    assert transition.confirms_after == Decimal("5")


def test_on_confirmed_rejects_zero_or_negative_delta(db, pattern):
    svc = BrandPatternStrengthService(db)
    with pytest.raises(ValueError):
        svc.on_confirmed(pattern.id, delta=0)
    with pytest.raises(ValueError):
        svc.on_confirmed(pattern.id, delta=Decimal("-1"))


def test_on_confirmed_does_not_reactivate_deactivated_pattern(db, pattern):
    svc = BrandPatternStrengthService(db)
    pattern.is_active = False
    db.add(pattern)
    db.commit()

    transition = svc.on_confirmed(pattern.id)
    db.commit()
    assert transition.is_active_before is False
    assert transition.is_active_after is False


def test_on_confirmed_raises_for_unknown_pattern(db):
    svc = BrandPatternStrengthService(db)
    with pytest.raises(BrandPatternNotFound):
        svc.on_confirmed(999999)


# ───────────────────────────────────────────────────────────────────
# on_rejected — deactivation thresholds
# ───────────────────────────────────────────────────────────────────


def test_on_rejected_increments_rejections(db, pattern):
    svc = BrandPatternStrengthService(db)
    transition = svc.on_rejected(pattern.id)
    db.commit()
    assert transition.event == "rejected"
    assert transition.rejections_before == Decimal("0")
    assert transition.rejections_after == Decimal("1")
    assert transition.is_active_after is True
    assert transition.deactivated is False


def test_on_rejected_deactivates_pattern_at_absolute_threshold(db, pattern):
    svc = BrandPatternStrengthService(db)
    for _ in range(int(DEACTIVATE_REJECTIONS) - 1):
        svc.on_rejected(pattern.id)
    db.refresh(pattern)
    assert pattern.is_active is True

    final = svc.on_rejected(pattern.id)
    db.commit()
    assert final.is_active_after is False
    assert final.deactivated is True


def test_on_rejected_deactivates_via_error_ratio(db, pattern):
    """High error-ratio (>50%) deactivates even before absolute threshold."""
    pattern.confirms = Decimal("3")
    db.add(pattern)
    db.commit()

    svc = BrandPatternStrengthService(db)
    # 3 confirms + 4 rejections → ratio 4/7 = 0.57 > 0.5 → deactivate.
    for _ in range(4):
        last = svc.on_rejected(pattern.id)
    db.commit()
    assert last.is_active_after is False


def test_on_rejected_keeps_pattern_active_on_balanced_history(db, pattern):
    """Many confirms make rejections survivable up to absolute threshold."""
    pattern.confirms = Decimal("100")
    db.add(pattern)
    db.commit()

    svc = BrandPatternStrengthService(db)
    # 4 rejections still under both abs-cap (5) and ratio-cap (0.5).
    for _ in range(4):
        svc.on_rejected(pattern.id)
    db.refresh(pattern)
    assert pattern.is_active is True


def test_on_rejected_raises_for_unknown_pattern(db):
    svc = BrandPatternStrengthService(db)
    with pytest.raises(BrandPatternNotFound):
        svc.on_rejected(999999)


def test_on_rejected_does_not_reactivate_already_inactive(db, pattern):
    pattern.is_active = False
    db.add(pattern)
    db.commit()

    svc = BrandPatternStrengthService(db)
    transition = svc.on_rejected(pattern.id)
    db.commit()
    assert transition.is_active_before is False
    assert transition.is_active_after is False
