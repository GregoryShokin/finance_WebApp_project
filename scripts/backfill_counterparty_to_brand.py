"""Backfill: stamp Brand on rows that have counterparty_id but no
user_confirmed_brand_id (Brand-Counterparty UI unification, v1.24).

Before v1.24, picking a «Контрагент» in the cluster modal stamped
`nd.counterparty_id` directly without going through the Brand layer.
Those rows now miss `user_confirmed_brand_id`, so the chronological
view still shows «Выбрать бренд» on them — the bug the unification
was meant to fix.

This script walks every active (non-committed) ImportRow with a
`counterparty_id` set but no `user_confirmed_brand_id`, finds or
creates a private Brand with the same name as the Counterparty,
and runs `confirm_brand_for_row` — which stamps brand_*, binds
fingerprint, learns text-pattern.

Idempotent: rows already carrying user_confirmed_brand_id are
skipped silently.

Usage:
    docker compose exec api python -m scripts.backfill_counterparty_to_brand --dry-run
    docker compose exec api python -m scripts.backfill_counterparty_to_brand --execute
    docker compose exec api python -m scripts.backfill_counterparty_to_brand --execute --user-id 1
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from app.core.db import SessionLocal
import app.models  # noqa: F401 — register all ORM models
from app.models.counterparty import Counterparty
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.services.brand_confirm_service import BrandConfirmError, BrandConfirmService
from app.services.brand_management_service import BrandManagementService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _find_or_create_brand(
    db,
    *,
    user_id: int,
    canonical_name: str,
) -> int:
    """Find existing private/global Brand by case-fold canonical_name, or
    create a new private one. Returns Brand.id."""
    repo = BrandRepository(db)
    target_fold = canonical_name.casefold()

    # Look at user's visible brands (private + global). Picker uses the
    # same scope, so this is consistent with what the UI would do.
    visible = repo.list_brands_for_user(user_id=user_id)
    for b in visible:
        if (b.canonical_name or "").casefold() == target_fold:
            return b.id

    # None matches — create private brand.
    mgmt = BrandManagementService(db)
    brand = mgmt.create_private_brand(
        user_id=user_id,
        canonical_name=canonical_name,
        category_hint=None,
    )
    db.commit()
    return brand.id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--user-id", type=int, default=None)
    args = parser.parse_args()

    if not (args.dry_run or args.execute):
        parser.error("Pass --dry-run or --execute")
    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute are mutually exclusive")

    db = SessionLocal()
    try:
        # Find candidate rows: active session, counterparty_id set, no brand confirm.
        rows_q = (
            db.query(ImportRow, ImportSession)
            .join(ImportSession, ImportSession.id == ImportRow.session_id)
            .filter(ImportSession.status != "committed")
        )
        if args.user_id is not None:
            rows_q = rows_q.filter(ImportSession.user_id == args.user_id)

        candidates: list[tuple[ImportRow, ImportSession, int, str]] = []
        for row, sess in rows_q.all():
            nd = row.normalized_data_json or {}
            if not isinstance(nd, dict):
                continue
            cp_id = nd.get("counterparty_id")
            if cp_id is None:
                continue
            if nd.get("user_confirmed_brand_id") is not None:
                continue
            cp = (
                db.query(Counterparty)
                .filter(
                    Counterparty.id == cp_id,
                    Counterparty.user_id == sess.user_id,
                )
                .first()
            )
            if cp is None:
                continue
            candidates.append((row, sess, sess.user_id, cp.name))

        logger.info("Candidate rows: %d", len(candidates))
        by_user_brand: Counter = Counter()
        for _, _, uid, name in candidates:
            by_user_brand[(uid, name)] += 1
        for (uid, name), n in by_user_brand.most_common():
            logger.info("  user=%s brand=%r → %d rows", uid, name, n)

        if args.dry_run:
            logger.info("\n(dry-run — nothing written)")
            return 0

        # Execute: per (user, brand_name) ensure Brand, then confirm-brand on each row.
        brand_id_cache: dict[tuple[int, str], int] = {}
        confirmer = BrandConfirmService(db)
        confirmed = 0
        failed = 0

        for row, sess, uid, name in candidates:
            key = (uid, name)
            if key not in brand_id_cache:
                brand_id_cache[key] = _find_or_create_brand(
                    db, user_id=uid, canonical_name=name,
                )
            brand_id = brand_id_cache[key]
            try:
                confirmer.confirm_brand_for_row(
                    user_id=uid, row_id=row.id, brand_id=brand_id,
                )
                confirmed += 1
            except BrandConfirmError as exc:
                logger.warning("row %s skipped: %s", row.id, exc)
                failed += 1
            except Exception:
                logger.exception("row %s failed", row.id)
                failed += 1
                db.rollback()

        logger.info(
            "\nDone: %d rows brand-confirmed, %d failed/skipped",
            confirmed, failed,
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
