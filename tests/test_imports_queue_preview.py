"""Tests for the unified moderation queue endpoint (v1.23).

`GET /imports/queue/preview` returns rows from ALL preview-ready sessions of
the user, enriched with source metadata (session_id, account_id, bank_code).
Sessions that are not yet ready (no account, status != preview_ready) are
silently excluded — they aren't moderation-ready.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_service import ImportService


def _mk_bank(db, *, code: str, name: str | None = None) -> Bank:
    b = Bank(name=name or code.title(), code=code, is_popular=False)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _mk_account(db, *, user_id: int, bank: Bank, name: str) -> Account:
    a = Account(
        user_id=user_id,
        bank_id=bank.id,
        name=name,
        currency="RUB",
        balance=Decimal("0"),
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
        user_id=user_id,
        filename=filename,
        source_type="csv",
        status=status,
        account_id=account_id,
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _mk_row(
    db,
    *,
    session_id: int,
    row_index: int,
    skeleton: str = "оплата pyaterochka",
    status: str = "ready",
) -> ImportRow:
    r = ImportRow(
        session_id=session_id,
        row_index=row_index,
        raw_data_json={"date": "2026-01-15"},
        normalized_data_json={
            "amount": "100.00",
            "direction": "expense",
            "transaction_date": "2026-01-15T12:00:00+00:00",
            "skeleton": skeleton,
            "fingerprint": f"fp{session_id:08d}{row_index:08d}",
        },
        status=status,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ──────────────────────────────────────────────────────────────────────
# Service-level tests
# ──────────────────────────────────────────────────────────────────────


def test_queue_preview_aggregates_rows_from_multiple_active_sessions(db, user):
    sber = _mk_bank(db, code="sber")
    tbank = _mk_bank(db, code="tbank")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта Сбер")
    tbank_acc = _mk_account(db, user_id=user.id, bank=tbank, name="Дебет Т-Банк")

    s1 = _mk_session(db, user_id=user.id, account_id=sber_acc.id, filename="sber.csv")
    s2 = _mk_session(db, user_id=user.id, account_id=tbank_acc.id, filename="tbank.csv")
    _mk_row(db, session_id=s1.id, row_index=1)
    _mk_row(db, session_id=s1.id, row_index=2)
    _mk_row(db, session_id=s2.id, row_index=1)

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    assert len(payload["sessions"]) == 2
    by_id = {s["session_id"]: s for s in payload["sessions"]}
    assert by_id[s1.id]["bank_code"] == "sber"
    assert by_id[s1.id]["account_name"] == "Карта Сбер"
    assert by_id[s2.id]["bank_code"] == "tbank"

    # 3 rows total, all with source metadata stamped.
    assert len(payload["rows"]) == 3
    assert all("session_id" in r for r in payload["rows"])
    assert all("bank_code" in r for r in payload["rows"])
    sber_rows = [r for r in payload["rows"] if r["session_id"] == s1.id]
    assert len(sber_rows) == 2
    assert all(r["bank_code"] == "sber" for r in sber_rows)


def test_queue_preview_excludes_session_without_account(db, user):
    """Session with status='preview_ready' but `account_id=None` is excluded
    — it can't be moderated until the user assigns an account."""
    sber = _mk_bank(db, code="sber")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    s_with_account = _mk_session(db, user_id=user.id, account_id=sber_acc.id)
    s_no_account = _mk_session(db, user_id=user.id, account_id=None, filename="orphan.csv")
    _mk_row(db, session_id=s_with_account.id, row_index=1)
    _mk_row(db, session_id=s_no_account.id, row_index=1)

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    session_ids = [s["session_id"] for s in payload["sessions"]]
    assert s_with_account.id in session_ids
    assert s_no_account.id not in session_ids
    assert all(r["session_id"] != s_no_account.id for r in payload["rows"])


def test_queue_preview_excludes_committed_session(db, user):
    """Session with status='committed' is filtered by list_active_sessions
    (the underlying repo method); it never reaches the queue."""
    sber = _mk_bank(db, code="sber")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    active = _mk_session(db, user_id=user.id, account_id=sber_acc.id)
    committed = _mk_session(
        db, user_id=user.id, account_id=sber_acc.id,
        status="committed", filename="old.csv",
    )
    _mk_row(db, session_id=active.id, row_index=1)
    _mk_row(db, session_id=committed.id, row_index=1)

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    session_ids = [s["session_id"] for s in payload["sessions"]]
    assert active.id in session_ids
    assert committed.id not in session_ids


def test_queue_preview_excludes_session_in_earlier_lifecycle_states(db, user):
    """Sessions in `queued` / `parsing` / `awaiting_account` etc. are
    filtered — only `preview_ready` reaches the unified moderator."""
    sber = _mk_bank(db, code="sber")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    ready = _mk_session(db, user_id=user.id, account_id=sber_acc.id)
    queued = _mk_session(
        db, user_id=user.id, account_id=sber_acc.id,
        status="queued", filename="q.csv",
    )
    _mk_row(db, session_id=ready.id, row_index=1)
    _mk_row(db, session_id=queued.id, row_index=1)

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    session_ids = [s["session_id"] for s in payload["sessions"]]
    assert ready.id in session_ids
    assert queued.id not in session_ids


def test_queue_preview_does_not_leak_other_users_sessions(db, user):
    from app.models.user import User
    other = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    sber = _mk_bank(db, code="sber")
    user_acc = _mk_account(db, user_id=user.id, bank=sber, name="Мой счёт")
    other_acc = _mk_account(db, user_id=other.id, bank=sber, name="Чужой счёт")
    user_session = _mk_session(db, user_id=user.id, account_id=user_acc.id)
    other_session = _mk_session(
        db, user_id=other.id, account_id=other_acc.id, filename="other.csv",
    )
    _mk_row(db, session_id=user_session.id, row_index=1)
    _mk_row(db, session_id=other_session.id, row_index=1)

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    session_ids = [s["session_id"] for s in payload["sessions"]]
    assert user_session.id in session_ids
    assert other_session.id not in session_ids


def test_queue_preview_summary_aggregates_across_sessions(db, user):
    """Summary counters sum row buckets across every admitted session."""
    sber = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    s1 = _mk_session(db, user_id=user.id, account_id=acc.id)
    s2 = _mk_session(db, user_id=user.id, account_id=acc.id, filename="two.csv")
    _mk_row(db, session_id=s1.id, row_index=1, status="ready")
    _mk_row(db, session_id=s1.id, row_index=2, status="warning")
    _mk_row(db, session_id=s2.id, row_index=1, status="ready")
    _mk_row(db, session_id=s2.id, row_index=2, status="error")

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    assert payload["summary"]["total_rows"] == 4
    assert payload["summary"]["ready_rows"] == 2
    assert payload["summary"]["warning_rows"] == 1
    assert payload["summary"]["error_rows"] == 1


def test_queue_preview_returns_empty_when_no_active_sessions(db, user):
    payload = ImportService(db).get_queue_preview(user_id=user.id)
    assert payload == {
        "sessions": [],
        "rows": [],
        "summary": {
            "total_rows": 0,
            "ready_rows": 0,
            "warning_rows": 0,
            "error_rows": 0,
            "duplicate_rows": 0,
            "skipped_rows": 0,
            "parked_rows": 0,
            "user_touched_rows": 0,
        },
    }
