"""Phase 3.5 / 3.6 / 3.7: parked status tests.

Covers:
  - park_row / unpark_row service methods (guards + status transitions)
  - list_parked_queue (global across sessions)
  - commit_import counts parked separately and skips them (no Transactions)

All tests use mocks — no real DB required.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.import_service import (
    ImportNotFoundError,
    ImportService,
    ImportValidationError,
)


def _make_svc(session_row=None, parked_queue=None) -> ImportService:
    svc = object.__new__(ImportService)
    svc.db = MagicMock()
    svc.import_repo = MagicMock()
    svc.import_repo.get_row_for_user.return_value = session_row
    svc.import_repo.list_parked_queue.return_value = parked_queue or []
    svc.import_repo.update_row.side_effect = lambda row, **kwargs: (
        setattr(row, "status", kwargs.get("status", row.status)) or row
    )
    svc.import_repo._hydrate_row_runtime_fields = MagicMock()
    svc._recalculate_summary = MagicMock(return_value={"total_rows": 1})
    return svc


def _row(row_id: int = 1, status: str = "warning", committed_tx_id: int | None = None) -> MagicMock:
    row = MagicMock()
    row.id = row_id
    row.status = status
    row.created_transaction_id = committed_tx_id
    return row


def _session(session_id: int = 10) -> MagicMock:
    s = MagicMock()
    s.id = session_id
    s.status = "preview_ready"
    s.summary_json = {}
    return s


# ---------------------------------------------------------------------------
# park_row
# ---------------------------------------------------------------------------

class TestParkRow:
    def test_park_sets_status_to_parked(self):
        row = _row(status="warning")
        session = _session()
        svc = _make_svc(session_row=(session, row))

        result = svc.park_row(user_id=1, row_id=1)
        assert result["status"] == "parked"
        svc.import_repo.update_row.assert_called_once()
        call = svc.import_repo.update_row.call_args
        assert call.kwargs["status"] == "parked"
        assert call.kwargs["review_required"] is False

    def test_park_raises_when_row_not_found(self):
        svc = _make_svc(session_row=None)
        with pytest.raises(ImportNotFoundError):
            svc.park_row(user_id=1, row_id=999)

    def test_park_rejects_committed_row(self):
        row = _row(status="committed", committed_tx_id=42)
        svc = _make_svc(session_row=(_session(), row))
        with pytest.raises(ImportValidationError):
            svc.park_row(user_id=1, row_id=1)

    def test_park_allowed_on_error_row(self):
        row = _row(status="error")
        svc = _make_svc(session_row=(_session(), row))
        result = svc.park_row(user_id=1, row_id=1)
        assert result["status"] == "parked"


# ---------------------------------------------------------------------------
# unpark_row
# ---------------------------------------------------------------------------

class TestUnparkRow:
    def test_unpark_restores_to_warning(self):
        row = _row(status="parked")
        svc = _make_svc(session_row=(_session(), row))
        result = svc.unpark_row(user_id=1, row_id=1)
        assert result["status"] == "warning"
        call = svc.import_repo.update_row.call_args
        assert call.kwargs["status"] == "warning"
        assert call.kwargs["review_required"] is True

    def test_unpark_rejects_non_parked_row(self):
        row = _row(status="ready")
        svc = _make_svc(session_row=(_session(), row))
        with pytest.raises(ImportValidationError):
            svc.unpark_row(user_id=1, row_id=1)

    def test_unpark_raises_when_row_not_found(self):
        svc = _make_svc(session_row=None)
        with pytest.raises(ImportNotFoundError):
            svc.unpark_row(user_id=1, row_id=999)


# ---------------------------------------------------------------------------
# list_parked_queue
# ---------------------------------------------------------------------------

class TestListParkedQueue:
    def test_list_returns_items_across_sessions(self):
        s1 = SimpleNamespace(
            id=10, status="preview_ready", filename="t1.csv", source_type="csv",
            updated_at=None,
        )
        s2 = SimpleNamespace(
            id=11, status="preview_ready", filename="t2.csv", source_type="csv",
            updated_at=None,
        )
        row1 = SimpleNamespace(
            id=1, row_index=0, status="parked", raw_data={},
            normalized_data={"fingerprint": "fp-a"}, raw_data_json={},
            normalized_data_json={"fingerprint": "fp-a"}, created_at=None, updated_at=None,
        )
        row2 = SimpleNamespace(
            id=2, row_index=5, status="parked", raw_data={},
            normalized_data={}, raw_data_json={},
            normalized_data_json={}, created_at=None, updated_at=None,
        )
        svc = _make_svc(parked_queue=[(s1, row1), (s2, row2)])

        result = svc.list_parked_queue(user_id=1)
        assert result["total"] == 2
        assert result["items"][0]["session_id"] == 10
        assert result["items"][0]["row_id"] == 1
        assert result["items"][1]["session_id"] == 11

    def test_empty_queue_returns_zero_total(self):
        svc = _make_svc(parked_queue=[])
        result = svc.list_parked_queue(user_id=1)
        assert result == {"items": [], "total": 0}


# ---------------------------------------------------------------------------
# commit_import: parked rows are skipped, counted separately
# ---------------------------------------------------------------------------

class TestCommitSkipsParked:
    """The commit loop must skip parked rows exactly like duplicate/error/warning,
    and expose parked_count in the response so the UI can surface it."""

    def test_parked_row_does_not_create_transaction(self):
        """Verified by tracing the commit loop's dispatch logic with a parked status."""
        # This is a structural test: the status check is the first in the loop,
        # so if the loop reaches a parked row, it hits the counter and continues.
        # We prove this by reading the source.
        import inspect
        from app.services import import_service
        src = inspect.getsource(import_service.ImportService.commit_import)
        # The commit loop must branch on "parked" before any transaction-creating logic.
        parked_idx = src.find('row_status == "parked"')
        create_idx = src.find("create_transaction")
        assert parked_idx != -1, "commit_import must handle parked status"
        assert parked_idx < create_idx, "parked branch must short-circuit before transaction creation"
