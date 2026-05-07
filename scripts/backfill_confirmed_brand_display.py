"""Backfill brand display fields on user-confirmed ImportRows (Brand registry post-Ph8b).

Before the post-Ph8b fix, `BrandConfirmService.confirm_brand_for_row`
stamped `user_confirmed_brand_id` but did NOT set the display fields
(`brand_canonical_name`, `brand_id`, `brand_slug`, `brand_category_hint`).
For rows that arrived to confirm via the resolver, those fields were
already present from the resolver match — display worked. But for rows
where the user used the «Выбрать бренд» picker on an unmatched row, the
canonical name never landed in `normalized_data_json`, so the UI kept
rendering the raw bank description even after confirm.

The fix in `brand_confirm_service.py` populates display fields for new
confirms. This script sweeps existing rows that were confirmed under
the old behaviour and patches their display fields from the brand they
were confirmed against.

Idempotent — safe to re-run. Skips rows that already have a non-empty
`brand_canonical_name`.

Usage:
    docker compose exec api python -m scripts.backfill_confirmed_brand_display --dry-run
    docker compose exec api python -m scripts.backfill_confirmed_brand_display --execute
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.import_row import ImportRow

logger = logging.getLogger(__name__)


def backfill(db: Session) -> dict[str, int]:
    counters = {
        "patched": 0,
        "skipped_no_brand_id": 0,
        "skipped_already_has_name": 0,
        "skipped_brand_missing": 0,
    }

    rows = db.query(ImportRow).all()
    brand_cache: dict[int, Brand | None] = {}

    for row in rows:
        nd = row.normalized_data_json or {}
        if not isinstance(nd, dict):
            continue
        confirmed_brand_id = nd.get("user_confirmed_brand_id")
        if not confirmed_brand_id:
            continue
        if nd.get("brand_canonical_name"):
            counters["skipped_already_has_name"] += 1
            continue

        brand_id = int(confirmed_brand_id)
        if brand_id not in brand_cache:
            brand_cache[brand_id] = (
                db.query(Brand).filter(Brand.id == brand_id).first()
            )
        brand = brand_cache[brand_id]
        if brand is None:
            counters["skipped_brand_missing"] += 1
            continue

        nd = dict(nd)
        nd["brand_id"] = brand.id
        nd["brand_slug"] = brand.slug
        nd["brand_canonical_name"] = brand.canonical_name
        nd["brand_category_hint"] = brand.category_hint
        row.normalized_data_json = nd
        db.add(row)
        counters["patched"] += 1

    return counters


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
            mode_label = "EXECUTED"
        else:
            db.rollback()
            mode_label = "DRY-RUN"
        logger.info(
            "%s. patched=%d skipped_already_has_name=%d "
            "skipped_brand_missing=%d",
            mode_label,
            stats["patched"],
            stats["skipped_already_has_name"],
            stats["skipped_brand_missing"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
