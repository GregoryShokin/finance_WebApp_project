"""One-shot sweep: stamp `normalized_data_json.brand_id` on active
ImportRow records that already carry `counterparty_id`.

Phase C step 2 prerequisite. Migration 0067 moved DB-level FKs
(brand_fingerprints, brand_identifiers, transactions.brand_id) but
left ImportRow.normalized_data_json untouched — its `counterparty_id`
stamps still point at Counterparty rows even though the merchant
entity is now Brand. Without this sweep, services refactored in step 2
to read `nd.brand_id` would see NULL on every active row that was
moderated under the pre-Phase-C UI.

Mapping per row:
  • If `nd.brand_id` already set → no-op.
  • Else read `nd.counterparty_id`, look up the Counterparty's name,
    resolve to a Brand visible to the user (private wins over global),
    create a private Brand if needed, stamp `nd.brand_id`.

The lookup logic mirrors migration 0067's `migrate_data` so this sweep
remains consistent with the data move that already happened. Brand
creation goes through `BrandManagementService.create_private_brand`,
which produces the same slug shape.

Idempotent. Safe to re-run. Only walks sessions with status != 'committed'
— committed rows already wrote their transactions and don't need
moderator-side updates anymore.

Usage:
    docker compose exec api python -m scripts.sweep_import_rows_cp_to_brand --dry-run
    docker compose exec api python -m scripts.sweep_import_rows_cp_to_brand --execute
    docker compose exec api python -m scripts.sweep_import_rows_cp_to_brand --execute --user-id 1
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from app.core.db import SessionLocal
import app.models  # noqa: F401 — register all ORM models
from app.models.brand import Brand
from app.models.counterparty import Counterparty
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.services.brand_management_service import BrandManagementService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _resolve_or_create_brand(
    db, *, user_id: int, canonical_name: str,
    cache: dict[tuple[int, str], int],
) -> int:
    """Find Brand visible to user by case-fold name, else create private.

    Same priority as migration 0067 — private wins over global.
    """
    key = (user_id, canonical_name.casefold())
    cached = cache.get(key)
    if cached is not None:
        return cached

    repo = BrandRepository(db)
    visible = repo.list_brands_for_user(user_id=user_id)
    private_match: Brand | None = None
    global_match: Brand | None = None
    target_fold = canonical_name.casefold()
    for b in visible:
        if (b.canonical_name or "").casefold() != target_fold:
            continue
        if not b.is_global and b.created_by_user_id == user_id:
            private_match = b
            break  # private wins, can stop scanning
        if b.is_global and global_match is None:
            global_match = b
    matched = private_match or global_match
    if matched is not None:
        cache[key] = matched.id
        return matched.id

    # Create new private brand (slug + per-user suffix via service).
    mgmt = BrandManagementService(db)
    brand = mgmt.create_private_brand(
        user_id=user_id,
        canonical_name=canonical_name,
        category_hint=None,
    )
    db.flush()
    cache[key] = brand.id
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
        # Active rows with a counterparty_id stamp and no brand_id stamp.
        rows_q = (
            db.query(ImportRow, ImportSession)
            .join(ImportSession, ImportSession.id == ImportRow.session_id)
            .filter(ImportSession.status != "committed")
        )
        if args.user_id is not None:
            rows_q = rows_q.filter(ImportSession.user_id == args.user_id)

        candidates: list[tuple[ImportRow, int, int]] = []  # (row, user_id, cp_id)
        for row, sess in rows_q.all():
            nd = row.normalized_data_json or {}
            if not isinstance(nd, dict):
                continue
            if nd.get("brand_id"):
                # Already brand-stamped (post-Phase-B confirm) — skip.
                continue
            cp_id = nd.get("counterparty_id")
            if cp_id is None:
                continue
            candidates.append((row, sess.user_id, int(cp_id)))

        if not candidates:
            logger.info("No rows to sweep.")
            return 0

        # Bulk-load the Counterparty rows referenced by candidate stamps.
        cp_ids = {cp_id for _, _, cp_id in candidates}
        cps = (
            db.query(Counterparty)
            .filter(Counterparty.id.in_(cp_ids))
            .all()
        )
        cp_by_id = {cp.id: cp for cp in cps}

        by_user_brand: Counter = Counter()
        plan: list[tuple[ImportRow, int, str]] = []  # (row, user_id, name)
        skipped_orphan = 0
        for row, uid, cp_id in candidates:
            cp = cp_by_id.get(cp_id)
            if cp is None or cp.user_id != uid:
                skipped_orphan += 1
                continue
            plan.append((row, uid, cp.name))
            by_user_brand[(uid, cp.name)] += 1

        logger.info(
            "Candidate rows: %d (orphan stamps skipped: %d)",
            len(plan), skipped_orphan,
        )
        for (uid, name), n in by_user_brand.most_common():
            logger.info("  user=%s brand=%r → %d rows", uid, name, n)

        if args.dry_run:
            logger.info("\n(dry-run — nothing written)")
            return 0

        # Execute.
        cache: dict[tuple[int, str], int] = {}
        stamped = 0
        for row, uid, name in plan:
            try:
                brand_id = _resolve_or_create_brand(
                    db, user_id=uid, canonical_name=name, cache=cache,
                )
            except Exception:
                logger.exception("brand resolve failed user=%s name=%r", uid, name)
                continue
            nd = dict(row.normalized_data_json or {})
            nd["brand_id"] = brand_id
            # Display fields: only fill when missing — confirmed rows
            # already carry these from the resolver / brand_confirm_service.
            if not nd.get("brand_canonical_name"):
                brand = db.query(Brand).filter(Brand.id == brand_id).first()
                if brand is not None:
                    nd["brand_slug"] = brand.slug
                    nd["brand_canonical_name"] = brand.canonical_name
                    nd["brand_category_hint"] = brand.category_hint
            row.normalized_data_json = nd
            db.add(row)
            stamped += 1
        db.commit()

        logger.info("\nDone: %d rows stamped with brand_id", stamped)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
