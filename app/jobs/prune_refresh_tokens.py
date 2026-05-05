"""Celery task: drop refresh-token rows whose `expires_at` has passed.

Without this, the table grows unbounded — every login adds a row, every
rotation adds a row. At ~30k tokens/user/year on an active session that
becomes millions of rows in months.

Scheduled daily at 04:30 UTC via `celery_app.conf.beat_schedule`. Pruning
expired tokens is safe regardless of revoked-state: a token past `expires_at`
can never be re-presented successfully (the JWT itself is also expired).
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


@celery_app.task(name="prune_refresh_tokens")
def prune_refresh_tokens() -> dict[str, Any]:
    from app.repositories.refresh_token_repository import RefreshTokenRepository

    db = SessionLocal()
    try:
        deleted = RefreshTokenRepository(db).prune_expired(now=datetime.now(timezone.utc))
        db.commit()
        logger.info("prune_refresh_tokens: deleted %s expired rows", deleted)
        return {"status": "ok", "deleted": deleted}
    except Exception as exc:
        logger.exception("prune_refresh_tokens failed")
        db.rollback()
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()
