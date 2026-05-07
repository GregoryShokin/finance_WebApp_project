"""Tests for `POST /imports/queue/commit-confirmed` (v1.23).

Atomic multi-session commit. Heavy commit pipeline (creating Transactions
across sessions, transfer-pair linking, rule strength updates) is covered
indirectly through the existing per-session `commit_import` tests; this file
focuses on the wrapper logic that's specific to cross-session commit:

  • Eligibility filter (status='preview_ready' AND account_id != None)
  • Cross-user isolation
  • Empty-queue early return
  • Per-session breakdown shape

The PostgreSQL-only `SELECT ... FOR UPDATE` lock is bypassed in
empty-queue paths (no rows to lock); for paths that hit the lock, this
test file only exercises against SQLite via empty-row sessions where
the per-row commit loop iterates zero times.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_session import ImportSession
from app.services.import_service import ImportService


def _mk_bank(db, *, code: str) -> Bank:
    b = Bank(name=code.title(), code=code, is_popular=False)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _mk_account(db, *, user_id: int, bank: Bank, name: str) -> Account:
    a = Account(
        user_id=user_id, bank_id=bank.id, name=name,
        currency="RUB", balance=Decimal("0"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_session(
    db,
    *,
    user_id: int,
    account_id: int | None,
    status: str = "preview_ready",
    filename: str = "t.csv",
) -> ImportSession:
    s = ImportSession(
        user_id=user_id, filename=filename, source_type="csv",
        status=status, account_id=account_id, file_content="",
        detected_columns=[], parse_settings={}, mapping_json={}, summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ──────────────────────────────────────────────────────────────────────


def test_commit_queue_returns_empty_totals_when_no_active_sessions(db, user):
    payload = ImportService(db).commit_queue_confirmed(user_id=user.id)
    assert payload == {
        "sessions": [],
        "totals": {
            "imported": 0, "skipped": 0, "duplicate": 0,
            "error": 0, "review": 0, "parked": 0,
        },
    }


def test_commit_queue_returns_empty_when_only_ineligible_sessions(db, user):
    """Sessions in queued / parsing / awaiting_account or without account
    are silently excluded — the response is still empty totals."""
    sber = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    # status=queued — excluded
    _mk_session(db, user_id=user.id, account_id=acc.id, status="queued")
    # account_id=None — excluded
    _mk_session(db, user_id=user.id, account_id=None, filename="orphan.csv")

    payload = ImportService(db).commit_queue_confirmed(user_id=user.id)

    assert payload["sessions"] == []
    assert all(v == 0 for v in payload["totals"].values())


def test_commit_queue_does_not_touch_other_users_sessions(db, user):
    """Cross-user isolation — `commit_queue_confirmed(user_id=A)` must not
    flip status on user B's sessions, even when both are preview_ready."""
    from app.models.user import User
    other = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    sber = _mk_bank(db, code="sber")
    user_acc = _mk_account(db, user_id=user.id, bank=sber, name="Мой счёт")
    other_acc = _mk_account(db, user_id=other.id, bank=sber, name="Чужой счёт")

    # Other user's session — must remain untouched.
    other_session = _mk_session(
        db, user_id=other.id, account_id=other_acc.id, filename="other.csv",
    )

    # Calling user has no rows in their (empty) eligible session — no commit
    # path runs, but the early-eligibility filter is exercised.
    user_session = _mk_session(db, user_id=user.id, account_id=user_acc.id)

    ImportService(db).commit_queue_confirmed(user_id=user.id)

    db.refresh(other_session)
    assert other_session.status == "preview_ready"  # untouched


def test_commit_queue_per_session_breakdown_shape(db, user):
    """When a session has zero rows, it doesn't appear in the per-session
    list — orchestrator skip is silent. Empty queue → empty list. Non-empty
    queue with empty session → still empty list (skipped)."""
    sber = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    # Eligible but empty — no rows created.
    _mk_session(db, user_id=user.id, account_id=acc.id)

    payload = ImportService(db).commit_queue_confirmed(user_id=user.id)

    # The eligible-but-empty session is silently skipped (orchestrator
    # is never called on empty rows list — see service code's `if not
    # import_rows: continue` guard).
    assert payload["sessions"] == []
    assert payload["totals"]["imported"] == 0
