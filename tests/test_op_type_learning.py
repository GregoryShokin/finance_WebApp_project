"""Tests for Этап 2 — Обучаемый operation_type.

Coverage matrix per Шаг 2.5 contract:
  1. Rule overrides op_type after threshold (apply_decisions priority slot 1)
  2. Rule deactivated after rejection threshold → enrichment fallback
  3. Co-existence: two rules same desc, different op_type
  4. Mixed bulk-apply cluster creates separate rules
  5a. Skip-list negative: transfer-row not learned
  5b. Skip-list positive: debt-row writes op_type into rule
  6. Idempotent bulk-upsert (single-transaction race via ON CONFLICT)
  7. NULLS NOT DISTINCT runtime invariant (smoke on migration 0062 — SQLite
     equivalent because SQLite treats NULLs as equal in UNIQUE)
  8. apply_decisions writes assignment_reasons for rule-based op_type
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models.category import Category
from app.models.transaction_category_rule import TransactionCategoryRule
from app.repositories.transaction_category_rule_repository import (
    TransactionCategoryRuleRepository,
)
from app.schemas.normalized_row import (
    DerivedRow,
    EnrichmentSuggestion,
    ParsedRow,
)
from app.services.import_normalization import apply_decisions
from app.services.rule_stats_committer import RuleStatsCommitter
from app.services.rule_strength_service import (
    CONFIRM_WEIGHT_READY,
    RuleStrengthService,
)


_NON_ANALYTICS_SKIP = {"transfer", "credit_disbursement", "refund"}


@pytest.fixture
def category(db, user):
    cat = Category(
        user_id=user.id,
        name="Зарплата",
        kind="income",
        priority="income_essential",
        regularity="regular",
        is_system=False,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@pytest.fixture
def category_other(db, user):
    cat = Category(
        user_id=user.id,
        name="Долги",
        kind="income",
        priority="income_volatile",
        regularity="irregular",
        is_system=False,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _make_active_rule(
    db,
    *,
    user,
    description: str,
    category_id: int,
    operation_type: str | None,
    confirms: int = 5,
) -> TransactionCategoryRule:
    """Create an already-active rule, bypassing the strength gate."""
    rule = TransactionCategoryRule(
        user_id=user.id,
        normalized_description=description,
        category_id=category_id,
        operation_type=operation_type,
        confirms=Decimal(confirms),
        rejections=Decimal("0"),
        is_active=True,
        scope="specific",
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _parsed(description: str = "Перевод от Иван И.") -> ParsedRow:
    from datetime import datetime, timezone

    return ParsedRow(
        date=datetime(2026, 5, 4, tzinfo=timezone.utc),
        amount=Decimal("1000"),
        currency="RUB",
        direction="income",
        description=description,
        raw_type=None,
        balance_after=None,
        source_reference=None,
        account_hint=None,
        counterparty_raw=None,
    )


def _derived(
    skeleton: str = "перевод от иван и",
    is_transfer_like: bool = False,
    is_refund_like: bool = False,
) -> DerivedRow:
    from app.services.import_normalizer_v2 import ExtractedTokens

    return DerivedRow(
        skeleton=skeleton,
        fingerprint="fp-x",
        tokens=ExtractedTokens(),
        transfer_identifier=None,
        is_transfer_like=is_transfer_like,
        is_refund_like=is_refund_like,
        refund_brand=None,
        requires_credit_split_hint=False,
        normalizer_version=2,
    )


def _suggestion(
    *,
    op_type: str = "regular",
    category_id: int | None = None,
    normalized_description: str = "перевод от иван и",
) -> EnrichmentSuggestion:
    return EnrichmentSuggestion(
        suggested_account_id=None,
        suggested_target_account_id=None,
        suggested_category_id=category_id,
        suggested_operation_type=op_type,
        suggested_type="income",
        normalized_description=normalized_description,
        assignment_confidence=0.65,
        assignment_reasons=[],
        review_reasons=[],
        needs_manual_review=False,
    )


# ─────────────────────────────────────────────────────────────────────────
# 1. Rule overrides op_type after threshold
# ─────────────────────────────────────────────────────────────────────────


def test_rule_overrides_op_type_after_threshold(db, user, category):
    rule = _make_active_rule(
        db,
        user=user,
        description="перевод от иван и",
        category_id=category.id,
        operation_type="debt",
        confirms=5,  # > RULE_ACTIVATE_CONFIRMS (default 2)
    )

    decision = apply_decisions(
        parsed=_parsed(),
        derived=_derived(),
        suggestion=_suggestion(category_id=category.id),
        category_rule=rule,
        session_account_id=1,
    )

    assert decision.operation_type == "debt"
    assert any(
        f"#{rule.id}" in r for r in decision.assignment_reasons
    ), f"reasons should reference rule id: {decision.assignment_reasons}"


def test_rule_below_threshold_does_not_override(db, user, category):
    rule = _make_active_rule(
        db,
        user=user,
        description="перевод от иван и",
        category_id=category.id,
        operation_type="debt",
        confirms=1,  # < RULE_ACTIVATE_CONFIRMS=2
    )
    rule.is_active = False  # not yet activated
    db.commit()

    decision = apply_decisions(
        parsed=_parsed(),
        derived=_derived(),
        suggestion=_suggestion(op_type="regular", category_id=category.id),
        category_rule=rule,
        session_account_id=1,
    )

    # Rule not active → falls back to suggestion.suggested_operation_type
    assert decision.operation_type == "regular"
    assert decision.assignment_reasons == []


# ─────────────────────────────────────────────────────────────────────────
# 2. Rule deactivated after rejection threshold → enrichment fallback
# ─────────────────────────────────────────────────────────────────────────


def test_rule_deactivated_by_rejections_falls_back_to_keyword(db, user, category):
    rule = _make_active_rule(
        db,
        user=user,
        description="перевод от иван и",
        category_id=category.id,
        operation_type="debt",
        confirms=5,
    )
    settings = Settings()

    svc = RuleStrengthService(db, settings)
    for _ in range(settings.RULE_DEACTIVATE_REJECTIONS):
        svc.on_rejected(rule.id)
    db.commit()
    db.refresh(rule)

    assert rule.is_active is False, "rule should be deactivated after rejections"

    decision = apply_decisions(
        parsed=_parsed(),
        derived=_derived(),
        suggestion=_suggestion(op_type="regular", category_id=category.id),
        category_rule=rule,
        session_account_id=1,
    )

    # Inactive rule → no priority-1 hit → suggestion wins.
    assert decision.operation_type == "regular"
    assert decision.assignment_reasons == []


# ─────────────────────────────────────────────────────────────────────────
# 3. Co-existence: two rules same desc, different op_type
# ─────────────────────────────────────────────────────────────────────────


def test_two_rules_same_desc_different_op_types_coexist(db, user, category, category_other):
    desc = "перевод от иван"
    rule_a = _make_active_rule(
        db,
        user=user,
        description=desc,
        category_id=category.id,
        operation_type="regular",
        confirms=5,
    )
    rule_b = _make_active_rule(
        db,
        user=user,
        description=desc,
        category_id=category_other.id,
        operation_type="debt",
        confirms=5,
    )

    rows = (
        db.query(TransactionCategoryRule)
        .filter(
            TransactionCategoryRule.user_id == user.id,
            TransactionCategoryRule.normalized_description == desc,
        )
        .all()
    )
    assert len(rows) == 2
    assert {r.id for r in rows} == {rule_a.id, rule_b.id}

    # 2-pass lookup honours op_type-bearing rules — both qualify with equal
    # confirms. Selection is deterministic by ORDER BY confirms DESC,
    # updated_at DESC, id DESC — newest id wins on equal confirms+updated_at.
    repo = TransactionCategoryRuleRepository(db)
    best = repo.get_best_rule(
        user_id=user.id,
        normalized_description=desc,
        want_op_type=True,
    )
    assert best is not None
    # rule_b was inserted second → higher id → wins on tie-break.
    assert best.id == rule_b.id, (
        f"on equal confirms expected newest-id wins (rule_b={rule_b.id}), got id={best.id}"
    )
    assert best.operation_type == "debt"


def test_get_best_rule_two_pass_prefers_op_type_over_legacy(db, user, category):
    desc = "magazin x"
    legacy = _make_active_rule(
        db,
        user=user,
        description=desc,
        category_id=category.id,
        operation_type=None,  # legacy NULL
        confirms=10,
    )
    learned = _make_active_rule(
        db,
        user=user,
        description=desc,
        category_id=category.id,
        operation_type="regular",
        confirms=3,  # lower confirms but explicit op_type
    )

    repo = TransactionCategoryRuleRepository(db)
    best = repo.get_best_rule(
        user_id=user.id,
        normalized_description=desc,
        want_op_type=True,
    )
    assert best is not None
    assert best.id == learned.id, "2-pass should prefer op_type-bearing rule"

    # Legacy mode (default want_op_type=False) — pure confirms ordering.
    legacy_best = repo.get_best_rule(user_id=user.id, normalized_description=desc)
    assert legacy_best is not None
    assert legacy_best.id == legacy.id, "legacy mode picks highest confirms"


def test_get_best_rule_falls_back_to_legacy_when_no_op_type_rule(db, user, category):
    desc = "magazin y"
    legacy = _make_active_rule(
        db,
        user=user,
        description=desc,
        category_id=category.id,
        operation_type=None,
        confirms=4,
    )

    repo = TransactionCategoryRuleRepository(db)
    best = repo.get_best_rule(
        user_id=user.id,
        normalized_description=desc,
        want_op_type=True,
    )
    assert best is not None
    assert best.id == legacy.id


# ─────────────────────────────────────────────────────────────────────────
# 4. Mixed bulk-apply cluster creates separate rules
# ─────────────────────────────────────────────────────────────────────────


def test_bulk_upsert_with_op_type_creates_separate_rules(db, user, category):
    repo = TransactionCategoryRuleRepository(db)
    desc = "ivan transfer"

    rule_regular, _ = repo.bulk_upsert(
        user_id=user.id,
        normalized_description=desc,
        category_id=category.id,
        confirms_delta=30,
        operation_type="regular",
    )
    rule_debt, _ = repo.bulk_upsert(
        user_id=user.id,
        normalized_description=desc,
        category_id=category.id,
        confirms_delta=20,
        operation_type="debt",
    )
    db.commit()

    assert rule_regular.id != rule_debt.id
    assert rule_regular.operation_type == "regular"
    assert rule_debt.operation_type == "debt"

    rows = (
        db.query(TransactionCategoryRule)
        .filter(
            TransactionCategoryRule.user_id == user.id,
            TransactionCategoryRule.normalized_description == desc,
            TransactionCategoryRule.category_id == category.id,
        )
        .all()
    )
    assert len(rows) == 2


# ─────────────────────────────────────────────────────────────────────────
# 5a. Skip-list negative: transfer-row not learned
# ─────────────────────────────────────────────────────────────────────────


def test_committer_skips_transfer_op_type(db, user, category):
    repo = TransactionCategoryRuleRepository(db)
    committer = RuleStatsCommitter(db, category_rule_repo=repo)

    committer.update_for_committed_row(
        user_id=user.id,
        normalized={
            "category_id": category.id,
            "normalized_description": "transfer iban",
            "description": "Перевод между счетами",
            "operation_type": "transfer",  # in skip-list
            "applied_rule_id": None,
            "applied_rule_category_id": None,
        },
        row_status="ready",
        bulk_acked=None,
        individually_confirmed=None,
        non_analytics_operation_types=_NON_ANALYTICS_SKIP,
    )
    db.commit()

    rules = (
        db.query(TransactionCategoryRule)
        .filter(
            TransactionCategoryRule.user_id == user.id,
            TransactionCategoryRule.normalized_description == "transfer iban",
        )
        .all()
    )
    assert rules == [], "transfer rows must not learn category-rules"


# ─────────────────────────────────────────────────────────────────────────
# 5b. Skip-list positive: debt-row writes op_type into rule
# ─────────────────────────────────────────────────────────────────────────


def test_committer_writes_op_type_for_debt(db, user, category):
    repo = TransactionCategoryRuleRepository(db)
    committer = RuleStatsCommitter(db, category_rule_repo=repo)

    committer.update_for_committed_row(
        user_id=user.id,
        normalized={
            "category_id": category.id,
            "normalized_description": "ivan debt skel",
            "description": "Перевод от Иван",
            "operation_type": "debt",  # NOT in skip-list
            "applied_rule_id": None,
            "applied_rule_category_id": None,
        },
        row_status="ready",
        bulk_acked=None,
        individually_confirmed=None,
        non_analytics_operation_types=_NON_ANALYTICS_SKIP,
    )
    db.commit()

    rules = (
        db.query(TransactionCategoryRule)
        .filter(
            TransactionCategoryRule.user_id == user.id,
            TransactionCategoryRule.normalized_description == "ivan debt skel",
        )
        .all()
    )
    assert len(rules) == 1
    assert rules[0].operation_type == "debt"


# ─────────────────────────────────────────────────────────────────────────
# 6. Idempotent bulk-upsert (single-transaction race via ON CONFLICT)
# ─────────────────────────────────────────────────────────────────────────


def test_bulk_upsert_idempotent_on_repeated_call(db, user, category):
    """Second bulk_upsert with same key returns SAME row, not a new one.

    Single-transaction race-protection via ON CONFLICT DO NOTHING + re-SELECT.
    Cross-request race (two browsers, two POSTs) is the Этап 3.3 idempotency-
    token's job, not this layer's.
    """
    repo = TransactionCategoryRuleRepository(db)
    desc = "ivan ssme"
    op = "debt"

    # bulk_upsert contract returns (rule, is_new). is_new=True iff the row
    # was created by this call; False iff it already existed (whether from
    # a prior call or a parallel race resolved via ON CONFLICT DO NOTHING).
    r1, is_new1 = repo.bulk_upsert(
        user_id=user.id,
        normalized_description=desc,
        category_id=category.id,
        confirms_delta=1,
        operation_type=op,
    )
    r2, is_new2 = repo.bulk_upsert(
        user_id=user.id,
        normalized_description=desc,
        category_id=category.id,
        confirms_delta=1,
        operation_type=op,
    )
    db.commit()

    assert is_new1 is True, "first call must create the rule"
    assert is_new2 is False, "second call must reuse, not duplicate"
    assert r1.id == r2.id

    rule_count = (
        db.query(TransactionCategoryRule)
        .filter(
            TransactionCategoryRule.user_id == user.id,
            TransactionCategoryRule.normalized_description == desc,
            TransactionCategoryRule.category_id == category.id,
            TransactionCategoryRule.operation_type == op,
        )
        .count()
    )
    assert rule_count == 1


# ─────────────────────────────────────────────────────────────────────────
# 7. NULLS NOT DISTINCT runtime invariant
# ─────────────────────────────────────────────────────────────────────────


def test_legacy_null_op_type_is_unique_via_nulls_not_distinct(db, user, category):
    """`NULLS NOT DISTINCT` invariant: two rows with op_type=NULL on the same
    (user, desc, cat) are rejected.

    Postgres-only — SQLite follows standard SQL where NULL != NULL inside
    UNIQUE indexes, so the duplicate INSERT succeeds on SQLite even though
    the schema declares the index. The migration-boundary `psql` smoke from
    Шаг 2.1 covers Postgres at the runtime level; this test is a guard for
    the test fixture engine.
    """
    if db.bind.dialect.name != "postgresql":
        pytest.skip("NULLS NOT DISTINCT is Postgres-only (SQLite treats NULL!=NULL in UNIQUE)")

    desc = "legacy null"
    _make_active_rule(
        db,
        user=user,
        description=desc,
        category_id=category.id,
        operation_type=None,
        confirms=1,
    )
    duplicate = TransactionCategoryRule(
        user_id=user.id,
        normalized_description=desc,
        category_id=category.id,
        operation_type=None,
        confirms=Decimal("1"),
        scope="specific",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ─────────────────────────────────────────────────────────────────────────
# 8. apply_decisions writes assignment_reasons for rule-based op_type
# ─────────────────────────────────────────────────────────────────────────


def test_apply_decisions_writes_assignment_reasons_for_rule_based_op_type(db, user, category):
    rule = _make_active_rule(
        db,
        user=user,
        description="перевод от иван и",
        category_id=category.id,
        operation_type="debt",
        confirms=5,
    )

    decision = apply_decisions(
        parsed=_parsed(),
        derived=_derived(),
        suggestion=_suggestion(category_id=category.id),
        category_rule=rule,
        session_account_id=1,
    )

    assert decision.assignment_reasons, "rule-based op_type must emit a reason"
    assert any("правил" in r.lower() for r in decision.assignment_reasons)
    assert any(str(rule.id) in r for r in decision.assignment_reasons)
