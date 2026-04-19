"""Celery job: monthly capital snapshot.

Runs on the 1st of each month at 03:00 UTC.
Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §2.3
Phase 3 Block A (2026-04-19).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.core.celery_app import celery_app
from app.core.db import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="monthly_capital_snapshot")
def run_monthly_capital_snapshot() -> dict:
    """Snapshot the previous completed month for all active users."""
    from app.models.user import User
    from app.services.capital_snapshot_service import CapitalSnapshotService

    db = SessionLocal()
    try:
        today = date.today()
        prev = date(today.year, today.month, 1) - timedelta(days=1)
        snapshot_month = date(prev.year, prev.month, 1)

        service = CapitalSnapshotService(db)
        user_ids = [row[0] for row in db.query(User.id).all()]
        created = 0
        for user_id in user_ids:
            try:
                service.create_snapshot_for_month(user_id, snapshot_month)
                created += 1
            except Exception as exc:
                logger.exception("Snapshot failed for user %s: %s", user_id, exc)

        db.commit()
        logger.info("Capital snapshots done: month=%s users=%d created=%d",
                    snapshot_month.isoformat(), len(user_ids), created)
        return {"month": snapshot_month.isoformat(), "users": len(user_ids), "created": created}
    finally:
        db.close()
