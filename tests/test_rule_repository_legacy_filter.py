"""PR1 §6.1 + §6.5: rule lookup excludes inactive + legacy-scope rules.

`get_best_rule` is the preview path's silent applicator — its filter is
the difference between a row landing in `ready` (silent application) and
landing in `warning` (user touch required). After PR1:

  * `is_active=False` rules NEVER match.
  * `scope IN ('bank', 'legacy_pattern')` rules NEVER match, even if
    flagged active by an old code path.
  * Only `scope IN ('specific', 'general')` is admitted to matching.

`get_active_legacy_rule` (cluster path 3) gets the same treatment.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.category import Category
from app.models.transaction_category_rule import TransactionCategoryRule
from app.repositories.transaction_category_rule_repository import (
    TransactionCategoryRuleRepository,
)


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


@pytest.fixture
def repo(db):
    return TransactionCategoryRuleRepository(db)


def _make_rule(
    db,
    user,
    category,
    *,
    normalized_description: str = "магазин продукты",
    scope: str = "general",
    is_active: bool = True,
    confirms: float = 5.0,
) -> TransactionCategoryRule:
    rule = TransactionCategoryRule(
        user_id=user.id,
        category_id=category.id,
        normalized_description=normalized_description,
        scope=scope,
        is_active=is_active,
        confirms=Decimal(str(confirms)),
        rejections=Decimal("0.00"),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


# ---------------------------------------------------------------------------
# get_best_rule: preview path
# ---------------------------------------------------------------------------


class TestGetBestRuleLegacyFilter:
    def test_inactive_rule_does_not_match(self, db, user, category, repo):
        _make_rule(db, user, category, scope="general", is_active=False)
        result = repo.get_best_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None, "inactive rule must not match (§6.5)"

    def test_legacy_pattern_rule_does_not_match_even_when_active(
        self, db, user, category, repo,
    ):
        _make_rule(db, user, category, scope="legacy_pattern", is_active=True)
        result = repo.get_best_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None, "legacy_pattern scope is deprecated, never matches"

    def test_bank_scope_rule_does_not_match_even_when_active(
        self, db, user, category, repo,
    ):
        _make_rule(db, user, category, scope="bank", is_active=True)
        result = repo.get_best_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None, "bank scope is deprecated, never matches"

    def test_general_active_rule_matches(self, db, user, category, repo):
        rule = _make_rule(db, user, category, scope="general", is_active=True)
        result = repo.get_best_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is not None
        assert result.id == rule.id

    def test_specific_active_rule_matches(self, db, user, category, repo):
        rule = _make_rule(db, user, category, scope="specific", is_active=True)
        result = repo.get_best_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is not None
        assert result.id == rule.id

    def test_inactive_general_does_not_match(self, db, user, category, repo):
        """Even the new `general` scope only matches when active."""
        _make_rule(db, user, category, scope="general", is_active=False)
        result = repo.get_best_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None


# ---------------------------------------------------------------------------
# get_active_legacy_rule: cluster path 3
# ---------------------------------------------------------------------------


class TestGetActiveLegacyRuleFilter:
    def test_legacy_pattern_scope_blocked(self, db, user, category, repo):
        _make_rule(
            db, user, category, scope="legacy_pattern", is_active=True,
        )
        result = repo.get_active_legacy_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None

    def test_bank_scope_blocked(self, db, user, category, repo):
        _make_rule(db, user, category, scope="bank", is_active=True)
        result = repo.get_active_legacy_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None

    def test_general_scope_passes(self, db, user, category, repo):
        rule = _make_rule(db, user, category, scope="general", is_active=True)
        result = repo.get_active_legacy_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is not None
        assert result.id == rule.id

    def test_inactive_blocked(self, db, user, category, repo):
        _make_rule(db, user, category, scope="general", is_active=False)
        result = repo.get_active_legacy_rule(
            user_id=user.id, normalized_description="магазин продукты"
        )
        assert result is None


# ---------------------------------------------------------------------------
# deactivate_legacy_rules.py — flips is_active on bank/legacy_pattern rules
# without touching scope or counters (§11.3 history preservation).
# ---------------------------------------------------------------------------


class TestDeactivateLegacyScript:
    def _build_mixed_set(self, db, user, category):
        return {
            "legacy_active": _make_rule(
                db, user, category,
                normalized_description="перевод абв", scope="legacy_pattern",
                is_active=True, confirms=4.0,
            ),
            "bank_active": _make_rule(
                db, user, category,
                normalized_description="перевод где", scope="bank",
                is_active=True, confirms=7.0,
            ),
            "legacy_already_inactive": _make_rule(
                db, user, category,
                normalized_description="перевод жзи", scope="legacy_pattern",
                is_active=False, confirms=2.0,
            ),
            "general_active": _make_rule(
                db, user, category,
                normalized_description="магазин продукты", scope="general",
                is_active=True, confirms=10.0,
            ),
        }

    def test_dry_run_does_not_persist(self, db, user, category, monkeypatch):
        """Dry-run reports what would change without committing."""
        from scripts import deactivate_legacy_rules as script
        rules = self._build_mixed_set(db, user, category)

        # Patch SessionLocal to reuse the test session.
        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))

        script.run(execute=False, user_filter=None)

        for r in rules.values():
            db.refresh(r)
        assert rules["legacy_active"].is_active is True
        assert rules["bank_active"].is_active is True
        assert rules["general_active"].is_active is True

    def test_execute_deactivates_only_legacy_scopes(
        self, db, user, category, monkeypatch,
    ):
        from scripts import deactivate_legacy_rules as script
        rules = self._build_mixed_set(db, user, category)

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, user_filter=None)

        for r in rules.values():
            db.refresh(r)
        # Legacy rules: is_active flipped to False, scope and counters intact.
        assert rules["legacy_active"].is_active is False
        assert rules["legacy_active"].scope == "legacy_pattern"
        assert rules["legacy_active"].confirms == Decimal("4.00")
        assert rules["bank_active"].is_active is False
        assert rules["bank_active"].scope == "bank"
        assert rules["bank_active"].confirms == Decimal("7.00")
        # Already-inactive: untouched.
        assert rules["legacy_already_inactive"].is_active is False
        # `general` rules: untouched.
        assert rules["general_active"].is_active is True
        assert rules["general_active"].confirms == Decimal("10.00")

    def test_user_filter_scopes_to_one_user(
        self, db, user, category, monkeypatch,
    ):
        """--user N flag deactivates legacy rules only for that user."""
        from app.models.user import User
        other = User(email="other@example.com", password_hash="x", is_active=True)
        db.add(other)
        db.commit()
        db.refresh(other)
        other_cat = Category(
            user_id=other.id, name="X", kind="expense",
            priority="expense_essential", regularity="regular",
        )
        db.add(other_cat)
        db.commit()
        db.refresh(other_cat)

        mine = _make_rule(
            db, user, category,
            normalized_description="перевод мой", scope="legacy_pattern",
            is_active=True,
        )
        theirs = _make_rule(
            db, other, other_cat,
            normalized_description="перевод чужой", scope="legacy_pattern",
            is_active=True,
        )

        from scripts import deactivate_legacy_rules as script
        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, user_filter=user.id)

        db.refresh(mine)
        db.refresh(theirs)
        assert mine.is_active is False
        assert theirs.is_active is True


class _NoCloseSession:
    """Wraps a test Session so the script's `with SessionLocal() as db`
    context block doesn't close the pytest fixture's session."""
    def __init__(self, real_session):
        self.s = real_session

    def __enter__(self):
        return self.s

    def __exit__(self, *exc):
        return False
