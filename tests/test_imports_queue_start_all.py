"""Tests for `POST /imports/queue/start-all` (v1.23).

Bulk-trigger of `auto_preview_import_session.delay()` for every analyzed
session that has account+mapping. Idempotent over already-previewed
sessions; reports counters so the UI can render a post-action toast.

Mocks the Celery enqueue (`auto_preview_import_session.delay`) — the
test verifies WHICH sessions trigger, not what the Celery task does.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

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


def _mk_account(db, *, user_id: int, bank: Bank, name: str = "Карта") -> Account:
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
    status: str,
    field_mapping: dict | None = None,
    filename: str = "t.csv",
) -> ImportSession:
    mapping = (
        {"field_mapping": field_mapping} if field_mapping is not None else {}
    )
    s = ImportSession(
        user_id=user_id, filename=filename, source_type="csv",
        status=status, account_id=account_id, file_content="",
        detected_columns=[], parse_settings={},
        mapping_json=mapping, summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ──────────────────────────────────────────────────────────────────────


def test_start_all_empty_queue_returns_zero_counters(db, user):
    payload = ImportService(db).start_queue_preview(user_id=user.id)
    assert payload == {"started": 0, "already_ready": 0, "skipped": 0}


def test_start_all_triggers_eligible_analyzed_sessions(db, user):
    sber = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=sber)

    # Two analyzed sessions with valid mapping — both should trigger.
    a1 = _mk_session(
        db, user_id=user.id, account_id=acc.id, status="analyzed",
        field_mapping={"date": "col1", "amount": "col2"},
    )
    a2 = _mk_session(
        db, user_id=user.id, account_id=acc.id, status="analyzed",
        field_mapping={"date": "col1", "amount": "col2"}, filename="b.csv",
    )

    triggered_ids: list[int] = []
    fake_task = type("T", (), {"delay": staticmethod(lambda sid: triggered_ids.append(sid))})

    with patch(
        "app.jobs.auto_preview_import_session.auto_preview_import_session",
        fake_task,
    ):
        payload = ImportService(db).start_queue_preview(user_id=user.id)

    assert payload == {"started": 2, "already_ready": 0, "skipped": 0}
    assert sorted(triggered_ids) == sorted([a1.id, a2.id])


def test_start_all_counts_already_ready_without_triggering(db, user):
    sber = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=sber)
    _mk_session(
        db, user_id=user.id, account_id=acc.id, status="preview_ready",
        field_mapping={"date": "col1", "amount": "col2"},
    )

    triggered: list[int] = []
    fake_task = type("T", (), {"delay": staticmethod(lambda sid: triggered.append(sid))})
    with patch(
        "app.jobs.auto_preview_import_session.auto_preview_import_session",
        fake_task,
    ):
        payload = ImportService(db).start_queue_preview(user_id=user.id)

    assert payload == {"started": 0, "already_ready": 1, "skipped": 0}
    assert triggered == []


def test_start_all_skips_session_without_account(db, user):
    sber = _mk_bank(db, code="sber")
    _mk_session(
        db, user_id=user.id, account_id=None, status="analyzed",
        field_mapping={"date": "col1", "amount": "col2"}, filename="orphan.csv",
    )

    triggered: list[int] = []
    fake_task = type("T", (), {"delay": staticmethod(lambda sid: triggered.append(sid))})
    with patch(
        "app.jobs.auto_preview_import_session.auto_preview_import_session",
        fake_task,
    ):
        payload = ImportService(db).start_queue_preview(user_id=user.id)

    assert payload == {"started": 0, "already_ready": 0, "skipped": 1}
    assert triggered == []


def test_start_all_skips_session_without_field_mapping(db, user):
    sber = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=sber)
    # mapping_json present but no `date` field — incomplete.
    _mk_session(
        db, user_id=user.id, account_id=acc.id, status="analyzed",
        field_mapping={"amount": "col2"},  # missing 'date'
    )

    triggered: list[int] = []
    fake_task = type("T", (), {"delay": staticmethod(lambda sid: triggered.append(sid))})
    with patch(
        "app.jobs.auto_preview_import_session.auto_preview_import_session",
        fake_task,
    ):
        payload = ImportService(db).start_queue_preview(user_id=user.id)

    assert payload == {"started": 0, "already_ready": 0, "skipped": 1}
    assert triggered == []


def test_start_all_does_not_touch_other_users_sessions(db, user):
    from app.models.user import User
    other = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    sber = _mk_bank(db, code="sber")
    other_acc = _mk_account(db, user_id=other.id, bank=sber)
    other_session = _mk_session(
        db, user_id=other.id, account_id=other_acc.id, status="analyzed",
        field_mapping={"date": "col1", "amount": "col2"}, filename="other.csv",
    )

    triggered: list[int] = []
    fake_task = type("T", (), {"delay": staticmethod(lambda sid: triggered.append(sid))})
    with patch(
        "app.jobs.auto_preview_import_session.auto_preview_import_session",
        fake_task,
    ):
        payload = ImportService(db).start_queue_preview(user_id=user.id)

    assert payload == {"started": 0, "already_ready": 0, "skipped": 0}
    assert other_session.id not in triggered
