"""Unit tests for app.services.rule_strength_service (Phase 2.3 of И-08).

Covers all 8 canonical transitions from the phase spec:
  1. Fresh rule (confirms=0, inactive, exact)         → 2× confirm → active
  2. Legacy rule (confirms=5, active, legacy_pattern) → 1× confirm → scope stays legacy_pattern
  3. Exact rule (confirms=3, rejections=0, bank_code) → 1× confirm → scope → bank
  4. Exact rule (confirms=3, rejections=0, no bank)   → 1× confirm → scope stays exact
  5. Active rule (confirms=10, rejections=0)          → 3× reject  → deactivated (absolute)
  6. Active rule (confirms=4, rejections=0)           → 1× reject  → still active (1/5 ≤ 0.3)
  7. Active rule (confirms=2, rejections=0)           → 1× reject  → deactivated (ratio 1/3 > 0.3)
  8. Deactivated rule (after reject)                  → 1× confirm → counters move, is_active stays False
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.category import Category
from app.models.transaction_category_rule import TransactionCategoryRule
from app.services.rule_strength_service import (
    RuleNotFound,
    RuleStrengthService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def category(db, user):
    cat = Category(
        user_id=user.id,
        name="Продукты",
        kind="expense",
        priority="expense_essential",
        regularity="regular",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _make_rule(
    db,
    user,
    category,
    *,
    normalized_description: str = "пятёрочка покупка",
    confirms: int = 0,
    rejections: int = 0,
    is_active: bool = False,
    scope: str = "exact",
    bank_code: str | None = None,
) -> TransactionCategoryRule:
    rule = TransactionCategoryRule(
        user_id=user.id,
        category_id=category.id,
        normalized_description=normalized_description,
        confirms=confirms,
        rejections=rejections,
        is_active=is_active,
        scope=scope,
        bank_code=bank_code,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@pytest.fixture
def service(db):
    return RuleStrengthService(db, settings)


# ---------------------------------------------------------------------------
# 1. Fresh rule → activation after threshold
# ---------------------------------------------------------------------------


def test_fresh_rule_activates_on_second_confirm(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=0, rejections=0, is_active=False, scope="exact",
    )

    t1 = service.on_confirmed(rule.id)
    assert t1.confirms_after == 1
    assert t1.is_active_after is False
    assert not t1.activated

    t2 = service.on_confirmed(rule.id)
    assert t2.confirms_after == 2
    assert t2.is_active_after is True
    assert t2.activated
    assert t2.event == "confirmed"


# ---------------------------------------------------------------------------
# 2. Legacy pattern — scope stays put even past generalize threshold
# ---------------------------------------------------------------------------


def test_legacy_pattern_scope_stays_legacy_on_confirm(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=5, rejections=0, is_active=True, scope="legacy_pattern",
        bank_code="tbank",
    )

    t = service.on_confirmed(rule.id)
    assert t.confirms_after == 6
    assert t.scope_after == "legacy_pattern"
    assert not t.generalized


# ---------------------------------------------------------------------------
# 3. Exact → bank when bank_code is set
# ---------------------------------------------------------------------------


def test_exact_generalizes_to_bank_when_bank_code_present(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=3, rejections=0, is_active=True, scope="exact",
        bank_code="tbank",
    )

    t = service.on_confirmed(rule.id)
    assert t.confirms_after == 4
    assert t.scope_before == "exact"
    assert t.scope_after == "bank"
    assert t.generalized


# ---------------------------------------------------------------------------
# 4. Exact with no bank_code stays exact
# ---------------------------------------------------------------------------


def test_exact_does_not_generalize_without_bank_code(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=3, rejections=0, is_active=True, scope="exact",
        bank_code=None,
    )

    t = service.on_confirmed(rule.id)
    assert t.confirms_after == 4
    assert t.scope_after == "exact"
    assert not t.generalized


# ---------------------------------------------------------------------------
# 5. Active rule deactivated on absolute rejection threshold
# ---------------------------------------------------------------------------


def test_active_rule_deactivates_on_three_rejections(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=10, rejections=0, is_active=True, scope="exact",
    )

    service.on_rejected(rule.id)
    service.on_rejected(rule.id)
    t = service.on_rejected(rule.id)

    assert t.rejections_after == 3
    assert t.is_active_after is False
    assert t.deactivated


# ---------------------------------------------------------------------------
# 6. One reject on a well-confirmed rule doesn't deactivate
# ---------------------------------------------------------------------------


def test_one_reject_on_high_confirms_keeps_active(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=4, rejections=0, is_active=True, scope="exact",
    )

    t = service.on_rejected(rule.id)
    # 1 / (4 + 1) = 0.2 <= 0.3 → still active
    assert t.rejections_after == 1
    assert t.is_active_after is True
    assert not t.deactivated


# ---------------------------------------------------------------------------
# 7. Low-confirm rule trips the error-ratio cap on one reject
# ---------------------------------------------------------------------------


def test_low_confirm_rule_deactivates_on_error_ratio(db, user, category, service):
    rule = _make_rule(
        db, user, category,
        confirms=2, rejections=0, is_active=True, scope="exact",
    )

    t = service.on_rejected(rule.id)
    # 1 / (2 + 1) ≈ 0.333 > 0.3 → deactivated by ratio
    assert t.rejections_after == 1
    assert t.is_active_after is False
    assert t.deactivated


# ---------------------------------------------------------------------------
# 8. Deactivated rule doesn't auto-reactivate on confirm
# ---------------------------------------------------------------------------


def test_deactivated_rule_stays_inactive_on_confirm(db, user, category, service):
    # Start from a deactivated-by-rejection rule.
    rule = _make_rule(
        db, user, category,
        confirms=10, rejections=3, is_active=False, scope="exact",
    )

    t = service.on_confirmed(rule.id)
    assert t.confirms_after == 11
    assert t.rejections_after == 3  # history preserved
    assert t.is_active_after is False
    assert not t.activated


# ---------------------------------------------------------------------------
# Guard: unknown rule_id
# ---------------------------------------------------------------------------


def test_unknown_rule_raises(db, service):
    with pytest.raises(RuleNotFound):
        service.on_confirmed(999_999)
    with pytest.raises(RuleNotFound):
        service.on_rejected(999_999)


# ---------------------------------------------------------------------------
# bulk-confirm: one call, N confirmations (И-08 Этап 2)
# ---------------------------------------------------------------------------


def test_bulk_confirm_activates_and_generalizes_in_one_call(
    db, user, category, service,
):
    """One bulk-apply click confirms N cluster rows, crossing both thresholds.

    Fresh exact rule with bank_code → confirms_delta=92 crosses both the
    activation (≥3) and generalization (≥7) thresholds, so the rule ends up
    active AND scope='bank' after a single call.
    """
    rule = _make_rule(db, user, category, bank_code="tbank")
    assert rule.is_active is False
    assert rule.scope == "exact"

    tx = service.on_confirmed(rule.id, confirms_delta=92)
    db.refresh(rule)

    assert rule.confirms == 92
    assert rule.is_active is True
    assert rule.scope == "bank"
    assert tx.activated is True
    assert tx.generalized is True
    assert tx.confirms_before == 0
    assert tx.confirms_after == 92


def test_bulk_confirm_delta_accumulates_on_existing_rule(
    db, user, category, service,
):
    """Existing rule with some confirms receives +N more from bulk-apply."""
    rule = _make_rule(db, user, category, confirms=2, is_active=False)

    service.on_confirmed(rule.id, confirms_delta=5)
    db.refresh(rule)

    assert rule.confirms == 7
    assert rule.is_active is True


def test_bulk_confirm_rejects_zero_and_negative_delta(db, user, category, service):
    rule = _make_rule(db, user, category)
    with pytest.raises(ValueError):
        service.on_confirmed(rule.id, confirms_delta=0)
    with pytest.raises(ValueError):
        service.on_confirmed(rule.id, confirms_delta=-3)


def test_bulk_confirm_on_deactivated_rule_does_not_reactivate(
    db, user, category, service,
):
    """Rule previously deactivated via rejections stays inactive even under
    a large bulk-confirm — same invariant as the single-confirm path."""
    rule = _make_rule(
        db, user, category,
        confirms=5, rejections=3, is_active=False,
    )
    service.on_confirmed(rule.id, confirms_delta=50)
    db.refresh(rule)

    assert rule.confirms == 55
    assert rule.is_active is False
