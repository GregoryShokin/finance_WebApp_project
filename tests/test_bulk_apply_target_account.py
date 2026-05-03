"""Bulk-apply with target_account_id (spec §13, v1.20).

When a cluster contains rows that share the same orphan-transfer hint
(suggested_target_account_id), the moderator can bulk-confirm them in one
click. The schema already supports `target_account_id` per-row in
BulkClusterRowUpdate; these tests verify the row editor (the unit BulkApply
delegates each per-row update to) writes it correctly and clears the hint.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.schemas.imports import BulkClusterRowUpdate, ImportRowUpdateRequest
from app.services.import_row_editor import ImportRowEditor
from app.repositories.import_repository import ImportRepository


@pytest.fixture
def src_account(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Сбер дебет",
        account_type="main", balance=Decimal("0"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def closed_target(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Тинькоф (закрыт)",
        account_type="main", balance=Decimal("0"),
        currency="RUB", is_active=False, is_credit=False,
        is_closed=True, closed_at=date(2026, 4, 1),
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def _session(db, user, account):
    s = ImportSession(
        user_id=user.id, account_id=account.id,
        filename="x.csv", file_content="", file_hash="hf",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def _orphan_row(db, *, sess, account, fingerprint, suggested_target_id, idx=0):
    nd = {
        "operation_type": "transfer",
        "account_id": account.id,
        "direction": "income",
        "type": "income",
        "amount": "1000",
        "currency": "RUB",
        "date": datetime(2026, 5, 1, 10, idx, tzinfo=timezone.utc).isoformat(),
        "description": "Поступление с карты Тинькофф",
        "skeleton": "поступление карты <BANK>",
        "fingerprint": fingerprint,
        "suggested_target_account_id": suggested_target_id,
        "suggested_target_account_name": "Тинькоф (закрыт)",
        "suggested_target_is_closed": True,
        "suggested_reason": "transfer-history 5/5",
    }
    row = ImportRow(
        session_id=sess.id, row_index=idx, status="warning",
        raw_data_json={}, normalized_data_json=nd,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Orchestrator: target_account_id is propagated to row.normalized_data
# ---------------------------------------------------------------------------


class TestBulkClusterRowUpdateSchema:
    def test_schema_accepts_target_account_id(self) -> None:
        """Per-row update payload supports target_account_id + operation_type
        (the bulk path the moderator uses for orphan-transfer confirmation).
        """
        upd = BulkClusterRowUpdate(
            row_id=1,
            operation_type="transfer",
            target_account_id=42,
        )
        assert upd.target_account_id == 42
        assert upd.operation_type == "transfer"


class TestRowEditorPropagatesTargetAccount:
    """BulkApplyOrchestrator delegates each row update to ImportRowEditor.
    Verify the per-row path stamps target_account_id and clears the hint —
    that's the entire surface bulk-apply needs from the row editor.
    """

    def test_confirm_with_target_writes_target_and_clears_hint(
        self, db, user, src_account, closed_target,
    ):
        sess = _session(db, user, src_account)
        row = _orphan_row(
            db, sess=sess, account=src_account,
            fingerprint="fp1", suggested_target_id=closed_target.id,
        )

        editor = ImportRowEditor(
            db,
            import_repo=ImportRepository(db),
            recalculate_summary_fn=lambda _sid: {},
            serialize_row_fn=lambda r: {"id": r.id},
        )
        editor.update_row(
            user_id=user.id,
            row_id=row.id,
            payload=ImportRowUpdateRequest(
                operation_type="transfer",
                target_account_id=closed_target.id,
                action="confirm",
            ),
        )

        db.refresh(row)
        nd = row.normalized_data_json or {}
        assert nd.get("operation_type") == "transfer"
        assert nd.get("target_account_id") == closed_target.id
        # Hint cleared per spec §5.2 v1.20
        assert "suggested_target_account_id" not in nd
        assert "suggested_target_account_name" not in nd
        assert "suggested_target_is_closed" not in nd

    def test_confirm_with_target_works_for_closed_account(
        self, db, user, src_account, closed_target,
    ):
        sess = _session(db, user, src_account)
        row = _orphan_row(
            db, sess=sess, account=src_account,
            fingerprint="fp2", suggested_target_id=closed_target.id,
        )

        editor = ImportRowEditor(
            db,
            import_repo=ImportRepository(db),
            recalculate_summary_fn=lambda _sid: {},
            serialize_row_fn=lambda r: {"id": r.id},
        )
        editor.update_row(
            user_id=user.id,
            row_id=row.id,
            payload=ImportRowUpdateRequest(
                operation_type="transfer",
                target_account_id=closed_target.id,
                action="confirm",
            ),
        )

        db.refresh(row)
        nd = row.normalized_data_json or {}
        assert nd.get("target_account_id") == closed_target.id
        assert nd.get("operation_type") == "transfer"
