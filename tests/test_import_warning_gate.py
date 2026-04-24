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
