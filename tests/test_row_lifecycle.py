"""Группа 7 (T24–T28) — жизненный цикл сессии и строк.

  • T26 — `delete_session` удаляет ImportSession + ImportRow по CASCADE.
  • T27 — park / unpark переводят между статусами `ready` ↔ `parked` ↔
    `warning`. Committed-строку нельзя park'нуть.
  • T28 — `exclude_row` помечает строку `skipped`, `unexclude_row`
    возвращает в `warning`. Committed-строку нельзя исключить.

T24 (повторный commit) и T25 (partial-error commit) требуют PostgreSQL —
`commit_import` использует `SELECT ... FOR UPDATE`, который SQLite не
поддерживает. Эти сценарии покрываются e2e-тестами против Postgres.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_service import (
    ImportNotFoundError,
    ImportService,
    ImportValidationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(db, user) -> ImportSession:
    s = ImportSession(
        user_id=user.id,
        filename="t.csv",
        source_type="csv",
        status="preview_ready",
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


def _make_row(db, session: ImportSession, *, row_index: int = 0,
              status: str = "ready") -> ImportRow:
    payload = {
        "amount": "100.00",
        "direction": "expense",
        "type": "expense",
        "description": "Test",
        "skeleton": "test",
        "transaction_date": datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
        "fingerprint": "abc",
        "operation_type": "regular",
    }
    row = ImportRow(
        session_id=session.id,
        row_index=row_index,
        raw_data_json={},
        normalized_data_json=payload,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# T26 — delete_session
# ---------------------------------------------------------------------------


def test_delete_session_removes_session(db, user):
    """T26: `delete_session` помечает сессию удалённой.

    На уровне БД ImportRow привязаны к ImportSession через
    `ondelete=CASCADE`. В Postgres rows исчезают автоматически.
    Тут проверяем сам контракт сервиса — сессии больше нет.
    Cascade-эффект на rows подтверждается интеграционно в Postgres-окружении.
    """
    session = _make_session(db, user)
    _make_row(db, session, row_index=0)

    ImportService(db).delete_session(user_id=user.id, session_id=session.id)

    assert db.query(ImportSession).filter(ImportSession.id == session.id).count() == 0


def test_delete_session_not_found_raises(db, user):
    with pytest.raises(ImportNotFoundError):
        ImportService(db).delete_session(user_id=user.id, session_id=99999)


def test_delete_session_isolated_per_user(db, user):
    """Удаление чужой сессии не должно работать (фильтр по user_id)."""
    from app.models.user import User
    other = User(email="o@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()

    other_session = _make_session(db, other)

    with pytest.raises(ImportNotFoundError):
        ImportService(db).delete_session(user_id=user.id, session_id=other_session.id)

    # Чужая сессия осталась
    assert (
        db.query(ImportSession).filter(ImportSession.id == other_session.id).first()
        is not None
    )


# ---------------------------------------------------------------------------
# T27 — park / unpark
# ---------------------------------------------------------------------------


def test_park_row_sets_parked_status(db, user):
    session = _make_session(db, user)
    row = _make_row(db, session, status="ready")

    result = ImportService(db).park_row(user_id=user.id, row_id=row.id)
    assert result["status"] == "parked"

    db.refresh(row)
    assert row.status == "parked"


def test_unpark_returns_row_to_warning(db, user):
    session = _make_session(db, user)
    row = _make_row(db, session, status="ready")
    svc = ImportService(db)

    svc.park_row(user_id=user.id, row_id=row.id)
    result = svc.unpark_row(user_id=user.id, row_id=row.id)

    assert result["status"] == "warning"


def test_unpark_rejects_non_parked_row(db, user):
    """Контракт: unpark — только для parked. ready-строки не пускает."""
    session = _make_session(db, user)
    row = _make_row(db, session, status="ready")

    with pytest.raises(ImportValidationError) as exc:
        ImportService(db).unpark_row(user_id=user.id, row_id=row.id)
    assert "отлож" in str(exc.value).lower()


def test_park_rejects_committed_row(db, user):
    """Committed-строку park нельзя — она уже стала транзакцией."""
    session = _make_session(db, user)
    row = _make_row(db, session, status="committed")
    row.created_transaction_id = 12345
    db.add(row)
    db.commit()

    with pytest.raises(ImportValidationError) as exc:
        ImportService(db).park_row(user_id=user.id, row_id=row.id)
    assert "Импортированную" in str(exc.value)


# ---------------------------------------------------------------------------
# T28 — exclude / unexclude
# ---------------------------------------------------------------------------


def test_exclude_row_sets_skipped_status(db, user):
    session = _make_session(db, user)
    row = _make_row(db, session, status="ready")

    result = ImportService(db).exclude_row(user_id=user.id, row_id=row.id)
    assert result["status"] == "skipped"


def test_exclude_rejects_committed_row(db, user):
    session = _make_session(db, user)
    row = _make_row(db, session, status="committed")
    row.created_transaction_id = 999
    db.add(row)
    db.commit()

    with pytest.raises(ImportValidationError):
        ImportService(db).exclude_row(user_id=user.id, row_id=row.id)


def test_unexclude_restores_skipped_to_warning(db, user):
    session = _make_session(db, user)
    row = _make_row(db, session, status="ready")
    svc = ImportService(db)

    svc.exclude_row(user_id=user.id, row_id=row.id)
    result = svc.unexclude_row(user_id=user.id, row_id=row.id)

    assert result["status"] == "warning"
