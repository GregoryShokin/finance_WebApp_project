"""One-shot: backfill Transaction.skeleton for rows created before migration 0052.

Context: §8.1 dedup now uses `skeleton` instead of `normalized_description`.
For existing transactions, `skeleton` is NULL and the dedup falls through to
a legacy `normalized_description` branch. To close that loop (and make
re-imports reliably hit the new skeleton-based index), we recompute the
skeleton for each historical row from its `description` + best-guess
`bank_code` and write it back.

Source signals, in priority order:
  1. If the transaction has an associated `ImportRow` whose
     `normalized_data_json.skeleton` is populated — use it verbatim.
  2. Otherwise, run `v2_normalize_skeleton(description, bank_code)` where
     `bank_code` is pulled from the account's linked Bank (may be None,
     which the normalizer tolerates).

Usage:
    docker compose exec api python -m scripts.backfill_transaction_skeleton            # dry-run
    docker compose exec api python -m scripts.backfill_transaction_skeleton --execute  # apply
    docker compose exec api python -m scripts.backfill_transaction_skeleton --user 42  # scope to one user
"""
from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.import_row import ImportRow
from app.models.transaction import Transaction
from app.services.import_normalizer_v2 import (
    extract_tokens as v2_extract_tokens,
    normalize_skeleton as v2_normalize_skeleton,
)


def _skeleton_from_import_row(row: ImportRow | None) -> str | None:
    if row is None:
        return None
    data: dict[str, Any] = getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
    skel = data.get("skeleton") if isinstance(data, dict) else None
    return str(skel).strip() if skel else None


def run(*, execute: bool, user_filter: int | None) -> None:
    with SessionLocal() as db:
        q = select(Transaction).where(Transaction.skeleton.is_(None))
        if user_filter is not None:
            q = q.where(Transaction.user_id == user_filter)

        total = 0
        filled_from_import = 0
        filled_from_description = 0
        skipped_no_source = 0

        for tx in db.execute(q).scalars().yield_per(500):
            total += 1

            # Path 1: if the tx was created from an ImportRow (common case for
            # anything coming out of the import pipeline), read the stored
            # skeleton straight out of its normalized_data.
            import_row = db.execute(
                select(ImportRow).where(ImportRow.created_transaction_id == tx.id).limit(1)
            ).scalar_one_or_none()
            skeleton = _skeleton_from_import_row(import_row)
            source = "import_row" if skeleton else None

            # Path 2: fall back to recomputing from description using the
            # v2 normalizer directly. Same pipeline used at import time —
            # extract tokens first, then produce the skeleton.
            if skeleton is None and tx.description:
                tokens = v2_extract_tokens(tx.description)
                skeleton = v2_normalize_skeleton(tx.description, tokens) or None
                if skeleton:
                    source = "description"

            if skeleton:
                if execute:
                    tx.skeleton = skeleton
                    db.add(tx)
                if source == "import_row":
                    filled_from_import += 1
                else:
                    filled_from_description += 1
            else:
                skipped_no_source += 1

        if execute:
            db.commit()

        print(f"Total transactions without skeleton: {total}")
        print(f"  filled from ImportRow:         {filled_from_import}")
        print(f"  filled from description (v2):  {filled_from_description}")
        print(f"  skipped (no source):           {skipped_no_source}")
        if not execute:
            print("\nDry-run. Pass --execute to persist.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--user", type=int, default=None, help="Limit backfill to one user_id")
    args = parser.parse_args()
    run(execute=args.execute, user_filter=args.user)


if __name__ == "__main__":
    main()
