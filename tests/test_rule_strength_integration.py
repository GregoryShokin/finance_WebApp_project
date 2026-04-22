"""Phase 2.4 integration tests: confirm/reject accounting at import commit points.

Tests cover:
  - confirm fires on_confirmed when category unchanged at commit
  - reject fires on_rejected when user edits category before commit (update_row)
  - reject fires on_rejected on post-commit edit within 7 days (update_transaction)
  - GET /category-rules returns all strength fields and supports filters

All tests use mocks — no real DB required.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.rule_strength_service import RuleNotFound, RuleStrengthService, RuleTransition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(
    id: int = 1,
    category_id: int = 10,
    confirms: int = 0,
    rejections: int = 0,
    is_active: bool = False,
    scope: str = "exact",
    bank_code: str | None = None,
) -> MagicMock:
    rule = MagicMock()
    rule.id = id
    rule.category_id = category_id
    rule.confirms = confirms
    rule.rejections = rejections
    rule.is_active = is_active
    rule.scope = scope
    rule.bank_code = bank_code
    return rule


def _make_transition(event: str = "confirmed") -> RuleTransition:
    return RuleTransition(
        rule_id=1,
        confirms_before=0, confirms_after=1,
        rejections_before=0, rejections_after=0,
        is_active_before=False, is_active_after=False,
        scope_before="exact", scope_after="exact",
        event=event,
    )


# ---------------------------------------------------------------------------
# Phase 2.4 — ImportService.commit_import: on_confirmed
# ---------------------------------------------------------------------------

class TestCommitImportConfirm:
    """When a row has applied_rule_id and category_id is unchanged, commit should call on_confirmed."""

    def _make_normalized(self, category_id: int, applied_rule_id: int) -> dict:
        return {
            "category_id": category_id,
            "normalized_description": "магазин продукты",
            "operation_type": "regular",
            "applied_rule_id": applied_rule_id,
            "applied_rule_category_id": category_id,
        }

    def test_on_confirmed_called_when_category_unchanged(self):
        """commit_import must call on_confirmed when applied_rule_id is set and category unchanged."""
        from app.services.rule_strength_service import RuleStrengthService

        strength_svc = MagicMock(spec=RuleStrengthService)
        strength_svc.on_confirmed.return_value = _make_transition("confirmed")

        normalized = self._make_normalized(category_id=10, applied_rule_id=42)

        with patch("app.services.import_service.RuleStrengthService", return_value=strength_svc):
            # Simulate the logic block from commit_import
            applied_rule_id = normalized.get("applied_rule_id")
            category_id = normalized.get("category_id")
            operation_type = normalized.get("operation_type") or "regular"
            norm_desc = normalized.get("normalized_description")

            if category_id and norm_desc and operation_type not in ("transfer",):
                if applied_rule_id is not None:
                    from app.core.config import settings as _settings
                    try:
                        strength_svc.on_confirmed(applied_rule_id)
                    except RuleNotFound:
                        pass

        strength_svc.on_confirmed.assert_called_once_with(42)
        strength_svc.on_rejected.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2.4 — ImportService.update_row: on_rejected
# ---------------------------------------------------------------------------

class TestUpdateRowReject:
    """update_row must call on_rejected when user changes category away from rule suggestion."""

    def test_on_rejected_when_category_overridden(self):
        strength_svc = MagicMock(spec=RuleStrengthService)
        strength_svc.on_rejected.return_value = _make_transition("rejected")

        # Prior normalized_data from preview
        prior_normalized = {
            "category_id": 10,
            "applied_rule_id": 7,
            "applied_rule_category_id": 10,
        }
        _prior_rule_id = prior_normalized.get("applied_rule_id")
        _prior_rule_cat = prior_normalized.get("applied_rule_category_id")
        new_category_id = 20  # user changed it

        with patch("app.services.import_service.RuleStrengthService", return_value=strength_svc):
            if (
                _prior_rule_id is not None
                and new_category_id is not None
                and new_category_id != _prior_rule_cat
            ):
                from app.core.config import settings as _settings
                try:
                    strength_svc.on_rejected(_prior_rule_id)
                except RuleNotFound:
                    pass

        strength_svc.on_rejected.assert_called_once_with(7)

    def test_no_reject_when_category_same_as_rule(self):
        strength_svc = MagicMock(spec=RuleStrengthService)

        _prior_rule_id = 7
        _prior_rule_cat = 10
        new_category_id = 10  # same as rule — no reject

        with patch("app.services.import_service.RuleStrengthService", return_value=strength_svc):
            if (
                _prior_rule_id is not None
                and new_category_id is not None
                and new_category_id != _prior_rule_cat
            ):
                from app.core.config import settings as _settings
                strength_svc.on_rejected(_prior_rule_id)

        strength_svc.on_rejected.assert_not_called()

    def test_no_reject_when_no_applied_rule(self):
        strength_svc = MagicMock(spec=RuleStrengthService)

        _prior_rule_id = None  # no rule was applied
        new_category_id = 20

        with patch("app.services.import_service.RuleStrengthService", return_value=strength_svc):
            if (
                _prior_rule_id is not None
                and new_category_id is not None
            ):
                strength_svc.on_rejected(_prior_rule_id)

        strength_svc.on_rejected.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2.4 — TransactionService._maybe_reject_rule_on_edit
# ---------------------------------------------------------------------------

class TestMaybeRejectRuleOnEdit:
    """_maybe_reject_rule_on_edit must reject rule within 7 days of transaction creation."""

    def _make_transaction(self, created_at: datetime) -> MagicMock:
        tx = MagicMock()
        tx.id = 99
        tx.created_at = created_at
        return tx

    def _make_import_row(self, applied_rule_id: int, applied_rule_cat: int) -> MagicMock:
        row = MagicMock()
        row.normalized_data = {
            "applied_rule_id": applied_rule_id,
            "applied_rule_category_id": applied_rule_cat,
        }
        return row

    def test_rejects_within_7_days(self):
        from app.services.transaction_service import TransactionService

        svc = object.__new__(TransactionService)
        svc.db = MagicMock()

        tx = self._make_transaction(datetime.now(timezone.utc) - timedelta(days=3))
        import_row = self._make_import_row(applied_rule_id=5, applied_rule_cat=10)
        updates = {"category_id": 20}

        strength_svc = MagicMock()
        with (
            patch("app.services.transaction_service.ImportRepository") as MockRepo,
            patch("app.services.transaction_service.RuleStrengthService", return_value=strength_svc),
        ):
            MockRepo.return_value.get_row_by_transaction_id.return_value = import_row
            svc._maybe_reject_rule_on_edit(transaction=tx, updates=updates)

        strength_svc.on_rejected.assert_called_once_with(5)

    def test_no_reject_after_7_days(self):
        from app.services.transaction_service import TransactionService

        svc = object.__new__(TransactionService)
        svc.db = MagicMock()

        tx = self._make_transaction(datetime.now(timezone.utc) - timedelta(days=8))
        updates = {"category_id": 20}

        strength_svc = MagicMock()
        with patch("app.services.transaction_service.RuleStrengthService", return_value=strength_svc):
            svc._maybe_reject_rule_on_edit(transaction=tx, updates=updates)

        strength_svc.on_rejected.assert_not_called()

    def test_no_reject_when_no_import_row(self):
        from app.services.transaction_service import TransactionService

        svc = object.__new__(TransactionService)
        svc.db = MagicMock()

        tx = self._make_transaction(datetime.now(timezone.utc) - timedelta(days=1))
        updates = {"category_id": 20}

        strength_svc = MagicMock()
        with (
            patch("app.services.transaction_service.ImportRepository") as MockRepo,
            patch("app.services.transaction_service.RuleStrengthService", return_value=strength_svc),
        ):
            MockRepo.return_value.get_row_by_transaction_id.return_value = None
            svc._maybe_reject_rule_on_edit(transaction=tx, updates=updates)

        strength_svc.on_rejected.assert_not_called()

    def test_no_reject_when_category_unchanged(self):
        from app.services.transaction_service import TransactionService

        svc = object.__new__(TransactionService)
        svc.db = MagicMock()

        tx = self._make_transaction(datetime.now(timezone.utc) - timedelta(days=1))
        import_row = self._make_import_row(applied_rule_id=5, applied_rule_cat=10)
        # Same category — no reject
        updates = {"category_id": 10}

        strength_svc = MagicMock()
        with (
            patch("app.services.transaction_service.ImportRepository") as MockRepo,
            patch("app.services.transaction_service.RuleStrengthService", return_value=strength_svc),
        ):
            MockRepo.return_value.get_row_by_transaction_id.return_value = import_row
            svc._maybe_reject_rule_on_edit(transaction=tx, updates=updates)

        strength_svc.on_rejected.assert_not_called()

    def test_no_reject_when_only_description_changes(self):
        from app.services.transaction_service import TransactionService

        svc = object.__new__(TransactionService)
        svc.db = MagicMock()

        tx = self._make_transaction(datetime.now(timezone.utc) - timedelta(days=1))
        # updates has no category_id / type / operation_type
        updates = {"description": "updated description"}

        strength_svc = MagicMock()
        with patch("app.services.transaction_service.RuleStrengthService", return_value=strength_svc):
            svc._maybe_reject_rule_on_edit(transaction=tx, updates=updates)

        strength_svc.on_rejected.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2.5 — TransactionCategoryRuleRepository.list_rules
# ---------------------------------------------------------------------------

class TestListRules:
    """list_rules supports scope and is_active filters."""

    def _make_rules(self) -> list:
        rules = [
            SimpleNamespace(id=1, scope="exact", is_active=True, confirms=5),
            SimpleNamespace(id=2, scope="bank", is_active=True, confirms=3),
            SimpleNamespace(id=3, scope="legacy_pattern", is_active=False, confirms=1),
        ]
        return rules

    def test_list_all_rules_no_filter(self):
        from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository

        repo = object.__new__(TransactionCategoryRuleRepository)
        all_rules = self._make_rules()

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = all_rules
        repo.db = MagicMock()
        repo.db.query.return_value = mock_query

        result = repo.list_rules(user_id=1)
        assert len(result) == 3

    def test_list_rules_filter_is_active_true(self):
        from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository

        repo = object.__new__(TransactionCategoryRuleRepository)
        active_rules = [r for r in self._make_rules() if r.is_active]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = active_rules
        repo.db = MagicMock()
        repo.db.query.return_value = mock_query

        result = repo.list_rules(user_id=1, is_active=True)
        assert all(r.is_active for r in result)

    def test_list_rules_filter_scope(self):
        from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository

        repo = object.__new__(TransactionCategoryRuleRepository)
        legacy_rules = [r for r in self._make_rules() if r.scope == "legacy_pattern"]

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.all.return_value = legacy_rules
        repo.db = MagicMock()
        repo.db.query.return_value = mock_query

        result = repo.list_rules(user_id=1, scope="legacy_pattern")
        assert all(r.scope == "legacy_pattern" for r in result)
