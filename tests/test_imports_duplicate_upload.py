"""Duplicate-statement upload UX tests for Этап 0.5.

Covers the explicit duplicate-detection signal in `ImportUploadResponse`:

  * fresh upload → no `action_required`,
  * uncommitted duplicate → `CHOOSE` + populated `existing_progress`,
  * committed-only duplicate → `WARN`,
  * `force_new=True` short-circuits both checks,
  * cross-user / cross-file isolation (file_hash is scoped per user),
  * race-condition warning when two parallel sessions slip past the dedup check.

Pattern: drive `ImportService.upload_source(...)` directly with a tiny CSV
through the real extractor → real recognizer → real DB session (SQLite from
conftest). This catches contract drift in `_session_to_upload_response`,
`find_by_file_hash`, and `count_session_progress` simultaneously, where pure
mocks would only check the service-shape we already wrote.
"""
from __future__ import annotations

import logging

import pytest

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.schemas.imports import DuplicateAction
from app.services.import_service import ImportService


CSV_BODY = b"date,amount,description\n2026-01-01,100.00,Coffee\n2026-01-02,50.00,Tea\n"
OTHER_CSV_BODY = b"date,amount,description\n2026-01-03,77.00,Lunch\n"


@pytest.fixture
def import_service(db):
    return ImportService(db)


def _upload(service: ImportService, *, user_id: int, body: bytes = CSV_BODY, force_new: bool = False) -> dict:
    return service.upload_source(
        user_id=user_id,
        filename="statement.csv",
        raw_bytes=body,
        delimiter=",",
        force_new=force_new,
    )


# ─── happy path ──────────────────────────────────────────────────────────────


def test_first_upload_creates_session_no_duplicate_marker(import_service, user):
    response = _upload(import_service, user_id=user.id)
    assert response["action_required"] is None
    assert response["existing_progress"] is None
    assert response["existing_status"] is None
    assert response["existing_created_at"] is None
    assert response["session_id"] is not None


# ─── active duplicate → CHOOSE ──────────────────────────────────────────────


def test_second_upload_same_file_returns_choose_action(import_service, user, db):
    first = _upload(import_service, user_id=user.id)
    second = _upload(import_service, user_id=user.id)

    assert second["action_required"] == DuplicateAction.CHOOSE
    # session_id of the duplicate response points at the EXISTING session,
    # not a new one — frontend uses this for "Открыть существующую".
    assert second["session_id"] == first["session_id"]
    # Only one ImportSession in DB (no parallel session created).
    sessions = db.query(ImportSession).filter(ImportSession.user_id == user.id).all()
    assert len(sessions) == 1
    # existing_progress is populated, all-zero on a fresh untouched session.
    progress = second["existing_progress"]
    assert progress is not None
    assert progress.committed_rows == 0
    assert progress.user_actions == 0
    assert progress.total_rows >= 0  # depends on whether preview ran; rows may be empty


# ─── committed duplicate → WARN ─────────────────────────────────────────────


def test_committed_session_returns_warn_action(import_service, user, db):
    first = _upload(import_service, user_id=user.id)
    # Mark the first session as committed via direct DB write — `commit_import`
    # would require a populated preview / account, which is out of scope here.
    session = db.query(ImportSession).filter(ImportSession.id == first["session_id"]).one()
    session.status = "committed"
    db.add(session)
    db.commit()

    second = _upload(import_service, user_id=user.id)
    assert second["action_required"] == DuplicateAction.WARN
    # WARN intentionally has no `existing_progress` — there is nothing to
    # lose by uploading as new (the old session is fully applied).
    assert second["existing_progress"] is None
    assert second["existing_status"] == "committed"
    assert second["existing_created_at"] is not None


# ─── force_new bypass ───────────────────────────────────────────────────────


def test_force_new_creates_new_session_despite_duplicate(import_service, user, db):
    first = _upload(import_service, user_id=user.id)
    second = _upload(import_service, user_id=user.id, force_new=True)

    assert second["action_required"] is None
    assert second["session_id"] != first["session_id"]
    # Both sessions persist — "Перезаписать" is intentionally NON-destructive
    # (see import_service.upload_file docstring).
    sessions = db.query(ImportSession).filter(ImportSession.user_id == user.id).all()
    assert len(sessions) == 2


# ─── isolation ──────────────────────────────────────────────────────────────


def test_different_users_dont_collide(import_service, user, db):
    from app.models.user import User

    other = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    first = _upload(import_service, user_id=user.id)
    second = _upload(import_service, user_id=other.id)

    # Different users → each gets their OWN session for the same file.
    assert second["action_required"] is None
    assert second["session_id"] != first["session_id"]


def test_different_files_dont_collide(import_service, user, db):
    first = _upload(import_service, user_id=user.id, body=CSV_BODY)
    second = _upload(import_service, user_id=user.id, body=OTHER_CSV_BODY)

    assert second["action_required"] is None
    assert second["session_id"] != first["session_id"]


# ─── payload contract ──────────────────────────────────────────────────────


def test_action_required_payload_contract_for_choose(import_service, user):
    _upload(import_service, user_id=user.id)
    response = _upload(import_service, user_id=user.id)

    # All four 0.5 fields must be present (not just `in` — explicitly keyed).
    for key in ("action_required", "existing_progress", "existing_status", "existing_created_at"):
        assert key in response, f"missing {key!r} in CHOOSE response"
    assert response["action_required"] == DuplicateAction.CHOOSE
    assert response["existing_progress"] is not None
    assert response["existing_status"] in ("uploaded", "analyzed", "preview_ready", "failed")


# ─── existing_progress counters ────────────────────────────────────────────


def test_existing_progress_counts_committed_and_user_actions(import_service, user, db):
    first = _upload(import_service, user_id=user.id)
    session_id = first["session_id"]

    # Inject 5 rows into the session at the row level. The extractor may or
    # may not have created any (depends on detection flow); we don't care —
    # we're measuring `count_session_progress` directly via response.
    db.query(ImportRow).filter(ImportRow.session_id == session_id).delete()
    db.commit()

    statuses = ["committed", "committed", "committed", "parked", "excluded", "ready", "warning", "error"]
    for idx, status in enumerate(statuses):
        db.add(ImportRow(
            session_id=session_id,
            row_index=idx,
            raw_data_json={},
            normalized_data_json={},
            status=status,
        ))
    db.commit()

    second = _upload(import_service, user_id=user.id)
    progress = second["existing_progress"]
    assert progress is not None
    assert progress.total_rows == len(statuses)
    assert progress.committed_rows == 3
    # `user_actions` is conservative (status NOT IN ('ready', 'error')) —
    # see ImportRepository.count_session_progress docstring. So:
    # committed (3) + parked (1) + excluded (1) + warning (1) = 6.
    assert progress.user_actions == 6


# ─── race condition warning ────────────────────────────────────────────────


def test_multiple_uncommitted_logs_warning(import_service, user, monkeypatch, caplog):
    """If two uncommitted sessions exist for one (user, file_hash), log a
    warning so we know whether to invest in a partial UNIQUE INDEX. Force
    the situation via monkeypatch — easier and more portable than racing
    two real upload threads against SQLite."""
    fake_a = ImportSession(
        id=9001,
        user_id=user.id,
        filename="dup-a.csv",
        source_type="csv",
        status="analyzed",
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )
    fake_b = ImportSession(
        id=9002,
        user_id=user.id,
        filename="dup-b.csv",
        source_type="csv",
        status="analyzed",
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )

    def _fake_find_by_file_hash(*, user_id, file_hash, include_committed):
        return [fake_a, fake_b]

    monkeypatch.setattr(
        import_service.import_repo, "find_by_file_hash", _fake_find_by_file_hash
    )
    # Stub the progress query so we don't touch the DB for the fake sessions.
    monkeypatch.setattr(
        import_service.import_repo,
        "count_session_progress",
        lambda *, session_id: {"total_rows": 0, "committed_rows": 0, "user_actions_count": 0},
    )

    with caplog.at_level(logging.WARNING, logger="app.services.import_service"):
        response = import_service.upload_source(
            user_id=user.id,
            filename="dup-a.csv",
            raw_bytes=CSV_BODY,
            delimiter=",",
        )

    assert any(
        "multiple uncommitted sessions" in rec.message.lower()
        for rec in caplog.records
    ), "race-condition warning was not emitted"
    # The actual response still works — we picked the first match for CHOOSE.
    assert response["action_required"] == DuplicateAction.CHOOSE
    assert response["session_id"] == fake_a.id
