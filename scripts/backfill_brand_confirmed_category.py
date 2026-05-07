"""One-shot backfill — apply category to brand-confirmed rows that have none.

Targets the regression introduced by the staged Brand-registry rollout: rows
confirmed during Ph7a (when confirm only stamped brand metadata) now sit
without a category. Ph7c learned to apply `brand.category_hint`, but only
on fresh confirms — historical rows need this manual sweep.

Side-effects per row:
  • normalized_data.category_id = <hint match>
  • normalized_data.counterparty_id = <find-or-create CP> (idempotent)
  • CounterpartyFingerprint binding (idempotent)

Skips rows with non-empty category_id (manual user override never gets
silently overwritten).

Usage:
    docker compose exec api python -m scripts.backfill_brand_confirmed_category --dry-run
    docker compose exec api python -m scripts.backfill_brand_confirmed_category --execute
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.services.brand_confirm_service import BrandConfirmService

logger = logging.getLogger(__name__)


def backfill(db: Session) -> dict[str, int]:
    counters: Counter[str] = Counter()

    rows = (
        db.query(ImportSession, ImportRow)
        .join(ImportRow, ImportRow.session_id == ImportSession.id)
        .filter(ImportSession.status != "committed")
        .all()
    )

    brand_repo = BrandRepository(db)
    cp_services: dict[int, BrandConfirmService] = {}

    for session, row in rows:
        nd = dict(row.normalized_data_json or {})
        confirmed_brand = nd.get("user_confirmed_brand_id")
        if not confirmed_brand:
            counters["skipped_not_confirmed"] += 1
            continue
        if nd.get("category_id"):
            counters["skipped_has_category"] += 1
            continue

        brand = brand_repo.get_brand(int(confirmed_brand))
        if brand is None:
            counters["skipped_brand_missing"] += 1
            continue
        if not brand.category_hint:
            counters["skipped_no_hint"] += 1
            continue

        svc = cp_services.get(session.user_id)
        if svc is None:
            svc = BrandConfirmService(db)
            cp_services[session.user_id] = svc

        # Resolve category by hint via service helper (handles case-fold).
        category = svc._lookup_category_by_hint(  # noqa: SLF001 — internal but stable
            user_id=session.user_id, brand=brand,
        )
        counterparty = svc._find_or_create_counterparty(  # noqa: SLF001
            user_id=session.user_id, brand=brand,
        )

        nd["counterparty_id"] = counterparty.id
        if category is not None:
            nd["category_id"] = category.id
            counters["filled_with_category"] += 1
        else:
            counters["filled_counterparty_only"] += 1
        row.normalized_data_json = nd
        db.add(row)

        svc._bind_fingerprint(  # noqa: SLF001
            user_id=session.user_id,
            fingerprint=nd.get("fingerprint"),
            counterparty_id=counterparty.id,
        )

    return dict(counters)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    from app.core.db import SessionLocal

    with SessionLocal() as db:
        stats = backfill(db)
        if args.execute:
            db.commit()
            label = "EXECUTED"
        else:
            db.rollback()
            label = "DRY-RUN"
        logger.info(
            "%s. filled_with_category=%d filled_counterparty_only=%d "
            "skipped_has_category=%d skipped_not_confirmed=%d "
            "skipped_brand_missing=%d skipped_no_hint=%d",
            label,
            stats.get("filled_with_category", 0),
            stats.get("filled_counterparty_only", 0),
            stats.get("skipped_has_category", 0),
            stats.get("skipped_not_confirmed", 0),
            stats.get("skipped_brand_missing", 0),
            stats.get("skipped_no_hint", 0),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
