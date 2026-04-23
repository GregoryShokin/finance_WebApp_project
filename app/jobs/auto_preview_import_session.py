"""Celery task: auto-run build_preview for a freshly uploaded import session.

Triggered by `upload_file` when the session was auto-mapped to a user account
(contract_number or statement_account_number match). Runs the full preview
pipeline — parse, enrich, normalize, transfer match — so that by the time the
user opens the queue the session is already `preview_ready` and transfers are
matched cross-session with other previously uploaded sessions.

Session-level status is tracked on `ImportSession.summary_json["auto_preview"]`:

    {
      "status": "pending" | "running" | "ready" | "failed" | "skipped",
      "started_at": iso,
      "finished_at": iso | null,
      "error": str | null,
    }

If auto-preview fails, the session stays in `status=analyzed` and the user
can still manually click "Продолжить выписку" to build preview with adjusted
mapping — that code path is unchanged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.celery_app import celery_app
from app.core.db import SessionLocal
# Eagerly load every ORM model (see note in moderate_import_session.py).
import app.models  # noqa: F401

logger = logging.getLogger(__name__)


@celery_app.task(name="auto_preview_import_session")
def auto_preview_import_session(session_id: int) -> dict[str, Any]:
    """Run build_preview for `session_id` using the auto-detected mapping.

    Returns a small status dict; authoritative state lives on
    `ImportSession.summary_json["auto_preview"]`.
    """
    from app.models.import_session import ImportSession
    from app.schemas.imports import ImportMappingRequest
    from app.services.import_service import ImportService, ImportValidationError

    db = SessionLocal()
    try:
        session = db.query(ImportSession).filter(ImportSession.id == session_id).first()
        if session is None:
            logger.warning("auto_preview_import_session: session %s not found", session_id)
            return {"status": "failed", "error": "session not found"}

        if session.status != "analyzed":
            # Another path already progressed the session — nothing to do.
            return {"status": "skipped", "reason": f"session status={session.status}"}

        mapping = session.mapping_json or {}
        field_mapping = mapping.get("field_mapping") or {}
        if not session.account_id or not field_mapping.get("date") or not field_mapping.get("amount"):
            _set_auto_preview_status(
                session,
                status="skipped",
                error="account not detected or mapping incomplete",
                finished=True,
            )
            db.add(session)
            db.commit()
            return {"status": "skipped", "reason": "incomplete auto-mapping"}

        _set_auto_preview_status(session, status="running", started_at=_now_iso())
        db.add(session)
        db.commit()

        service = ImportService(db)
        suggested_dates = mapping.get("suggested_date_formats") or []
        date_format = suggested_dates[0] if suggested_dates else "%Y-%m-%d"
        payload = ImportMappingRequest(
            account_id=session.account_id,
            currency=(session.currency or "RUB").upper(),
            date_format=date_format,
            table_name=mapping.get("selected_table"),
            field_mapping=field_mapping,
            skip_duplicates=True,
        )

        try:
            service.build_preview(
                user_id=session.user_id,
                session_id=session.id,
                payload=payload,
            )
        except ImportValidationError as exc:
            logger.warning("auto_preview_import_session %s validation: %s", session_id, exc)
            session = db.query(ImportSession).filter(ImportSession.id == session_id).first()
            if session is not None:
                _set_auto_preview_status(session, status="failed", error=str(exc), finished=True)
                db.add(session)
                db.commit()
            return {"status": "failed", "error": str(exc)}
        except Exception as exc:
            logger.exception("auto_preview_import_session %s failed", session_id)
            db.rollback()
            session = db.query(ImportSession).filter(ImportSession.id == session_id).first()
            if session is not None:
                _set_auto_preview_status(session, status="failed", error=str(exc), finished=True)
                db.add(session)
                db.commit()
            return {"status": "failed", "error": str(exc)}

        # build_preview already committed. Re-fetch, mark auto_preview ready.
        session = db.query(ImportSession).filter(ImportSession.id == session_id).first()
        user_id = session.user_id if session is not None else None
        if session is not None:
            _set_auto_preview_status(session, status="ready", finished=True)
            db.add(session)
            db.commit()

        # Trigger the debounced global transfer matcher. `build_preview` already
        # fires the same trigger, but calling it again here is harmless — the
        # debounce layer coalesces rapid successive calls into a single run.
        if user_id is not None:
            try:
                from app.jobs.transfer_matcher_debounced import schedule_transfer_match
                schedule_transfer_match(user_id)
            except Exception:
                logger.exception("schedule_transfer_match failed for user %s", user_id)

        return {"status": "ready"}
    finally:
        db.close()


def _set_auto_preview_status(
    session,
    *,
    status: str,
    started_at: str | None = None,
    error: str | None = None,
    finished: bool = False,
) -> None:
    summary = dict(session.summary_json or {})
    current = dict(summary.get("auto_preview") or {})
    current["status"] = status
    if started_at is not None:
        current["started_at"] = started_at
    if finished:
        current["finished_at"] = _now_iso()
    if error is not None:
        current["error"] = error
    elif status == "ready":
        current["error"] = None
    summary["auto_preview"] = current
    session.summary_json = summary


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
