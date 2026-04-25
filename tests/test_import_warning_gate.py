"""Spec v1.1 warning/error classification + commit gate (§5.2, §5.4, §10.2).

Covers:
- `account_id` missing → `error` (promoted from warning).
- Transfer with only one known account → `error`.
- Warning rows DO NOT commit without explicit user touch
  (`cluster_bulk_acked_at` or `user_confirmed_at`).
- Bulk-ack warning commit → Case B weight 0.5.
- Individual-confirm warning commit → Case A weight 1.0.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.import_service import ImportService


# ---------------------------------------------------------------------------
# §5.2: promoted error triggers
# ---------------------------------------------------------------------------


def test_missing_account_id_is_error_not_warning(db):
    svc = ImportService(db)
    normalized = {
        "account_id": None,
        "amount": "100.00",
        "operation_type": "regular",
        "transaction_date": "2026-04-20T12:00:00+00:00",
    }
    status, issues = svc._validate_manual_row(
        normalized=normalized,
        current_status="ready",
        issues=[],
        allow_ready_status=True,
    )
    assert status == "error", f"expected 'error', got {status!r}; issues={issues}"


def test_transfer_without_target_account_is_error(db, regular_account):
    svc = ImportService(db)
    normalized = {
        "account_id": regular_account.id,
        "amount": "500.00",
        "operation_type": "transfer",
        "type": "expense",
        "target_account_id": None,
        "transaction_date": "2026-04-20T12:00:00+00:00",
    }
    status, issues = svc._validate_manual_row(
        normalized=normalized,
        current_status="ready",
        issues=[],
        allow_ready_status=True,
    )
    assert status == "error", f"expected 'error', got {status!r}; issues={issues}"


def test_transfer_with_both_accounts_passes(db, regular_account, credit_account):
    svc = ImportService(db)
    normalized = {
        "account_id": regular_account.id,
        "amount": "500.00",
        "operation_type": "transfer",
        "type": "expense",
        "target_account_id": credit_account.id,
        "transaction_date": "2026-04-20T12:00:00+00:00",
    }
    status, _ = svc._validate_manual_row(
        normalized=normalized,
        current_status="ready",
        issues=[],
        allow_ready_status=True,
    )
    # Passes account + transfer validation; may still be warning from other
    # checks (missing category on regular would fire; transfer doesn't need
    # category). The only assertion here is that it's NOT error.
    assert status != "error", f"expected non-error, got {status!r}"


# ---------------------------------------------------------------------------
# §5.4: commit gate for warning rows
# ---------------------------------------------------------------------------


# Commit-flow scenarios for the warning gate (bulk-ack vs individual confirm,
# import_ready_only strict mode) live in the PG integration suite — they
# depend on FOR UPDATE locking which SQLite can't express. The gate predicate
# itself is exercised by the e2e moderation pipeline suite on real PG.


# ---------------------------------------------------------------------------
# §12.1 / §5.2 v1.1 trigger 6: transfer integrity gate on the PREVIEW path.
# The helper is pure so we unit-test it directly, independent of the full
# build_preview pipeline.
# ---------------------------------------------------------------------------


class TestPreviewTransferIntegrityGate:
    def test_transfer_without_target_escalates_to_error(self):
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": 1,
                "target_account_id": None,
                "type": "expense",
            },
            current_status="ready",
            issues=[],
        )
        assert status == "error", f"expected 'error', got {status!r}"
        assert issues and any("получателя" in i for i in issues)

    def test_transfer_without_source_escalates_to_error(self):
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": None,
                "target_account_id": 2,
                "type": "income",
            },
            current_status="ready",
            issues=[],
        )
        assert status == "error"
        assert any("из выписки" in i for i in issues)

    def test_transfer_without_both_sides_escalates_to_error(self):
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": None,
                "target_account_id": None,
                "type": "expense",
            },
            current_status="ready",
            issues=[],
        )
        assert status == "error"
        assert any("оба счёта" in i for i in issues)

    def test_transfer_income_without_source_has_sender_phrasing(self):
        """Income transfer → the missing side is the SENDER."""
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": 1,
                "target_account_id": None,
                "type": "income",
            },
            current_status="ready",
            issues=[],
        )
        assert status == "error"
        assert any("отправителя" in i for i in issues)

    def test_transfer_with_both_accounts_passes_through(self):
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": 1,
                "target_account_id": 2,
                "type": "expense",
            },
            current_status="ready",
            issues=[],
        )
        # Gate is silent when data is complete — downstream logic decides.
        assert status == "ready"
        assert issues == []

    def test_non_transfer_is_ignored(self):
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "regular",
                "account_id": None,
                "target_account_id": None,
                "type": "expense",
            },
            current_status="ready",
            issues=[],
        )
        # Regular-expense row with a missing account is someone else's
        # problem (separate §5.2 trigger). The transfer gate must not fire.
        assert status == "ready"
        assert issues == []

    def test_duplicate_status_is_sticky_even_on_failed_transfer(self):
        """Duplicate is terminal (§8.3); the gate must not overwrite it."""
        status, issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": 1,
                "target_account_id": None,
                "type": "expense",
            },
            current_status="duplicate",
            issues=[],
        )
        assert status == "duplicate"
        # Issue is still recorded for visibility even though status stays.
        assert issues and any("получателя" in i for i in issues)

    def test_idempotent_issue_append(self):
        """Calling the gate twice with the same issue list mustn't duplicate."""
        first_status, first_issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": 1,
                "target_account_id": None,
                "type": "expense",
            },
            current_status="ready",
            issues=[],
        )
        second_status, second_issues = ImportService._gate_transfer_integrity(
            normalized={
                "operation_type": "transfer",
                "account_id": 1,
                "target_account_id": None,
                "type": "expense",
            },
            current_status=first_status,
            issues=first_issues,
        )
        assert second_status == "error"
        assert len(second_issues) == 1
