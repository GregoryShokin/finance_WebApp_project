"""Backfill brand_* fields on existing ImportRow records (Brand registry Ph7c).

Runs the BrandResolverService over every non-committed ImportRow that
already has a skeleton + tokens but lacks brand_id (or carries a stale
match from before threshold tuning / seed updates) and patches
normalized_data with the fresh resolver verdict.

Idempotent — safe to re-run after seed updates or threshold changes.
Rows where the user already confirmed/rejected a brand are NOT touched
(user choice always wins over a re-derivation).

Usage:
    docker compose exec api python -m scripts.backfill_brand_match --dry-run
    docker compose exec api python -m scripts.backfill_brand_match --execute
    docker compose exec api python -m scripts.backfill_brand_match --execute --user-id 5
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.brand_resolver_service import BrandResolverService
from app.services.import_normalizer_v2 import ExtractedTokens

logger = logging.getLogger(__name__)


def _tokens_from_normalized(nd: dict) -> ExtractedTokens:
    """Re-hydrate ExtractedTokens from the persisted JSON shape (TokensV2)."""
    raw = nd.get("tokens") or {}
    return ExtractedTokens(
        phone=raw.get("phone"),
        contract=raw.get("contract"),
        iban=raw.get("iban"),
        card=raw.get("card"),
        person_name=None,
        counterparty_org=raw.get("counterparty_org"),
        sbp_merchant_id=raw.get("sbp_merchant_id"),
        # Legacy field name "terminal_id" was renamed to "card_last4" — read
        # both for backward compat with rows persisted before the rename.
        card_last4=raw.get("card_last4") or raw.get("terminal_id"),
    )


def _eligible_rows(db: Session, *, user_id: int | None) -> Iterable[tuple[ImportSession, ImportRow]]:
    q = (
        db.query(ImportSession, ImportRow)
        .join(ImportRow, ImportRow.session_id == ImportSession.id)
        .filter(ImportSession.status != "committed")
    )
    if user_id is not None:
        q = q.filter(ImportSession.user_id == user_id)
    return q.all()


def backfill(db: Session, *, user_id: int | None) -> dict[str, int]:
    counters: Counter[str] = Counter()
    user_resolvers: dict[int, BrandResolverService] = {}

    for session, row in _eligible_rows(db, user_id=user_id):
        nd = dict(row.normalized_data_json or {})
        skeleton = (nd.get("skeleton") or "").strip()
        if not skeleton:
            counters["skipped_no_skeleton"] += 1
            continue
        if nd.get("user_confirmed_brand_id") or nd.get("user_rejected_brand_id"):
            counters["skipped_user_decision"] += 1
            continue

        resolver = user_resolvers.get(session.user_id)
        if resolver is None:
            resolver = BrandResolverService(db)
            user_resolvers[session.user_id] = resolver

        match = resolver.resolve(
            skeleton=skeleton,
            tokens=_tokens_from_normalized(nd),
            user_id=session.user_id,
        )

        before = (
            nd.get("brand_id"), nd.get("brand_pattern_id"),
            nd.get("brand_confidence"),
        )

        if match is None:
            after = (None, None, None)
            for key in (
                "brand_id", "brand_slug", "brand_canonical_name",
                "brand_category_hint", "brand_pattern_id", "brand_kind",
                "brand_confidence",
            ):
                nd.pop(key, None)
        else:
            nd["brand_id"] = match.brand_id
            nd["brand_slug"] = match.brand_slug
            nd["brand_canonical_name"] = match.canonical_name
            nd["brand_category_hint"] = match.category_hint
            nd["brand_pattern_id"] = match.pattern_id
            nd["brand_kind"] = match.kind
            nd["brand_confidence"] = match.confidence
            after = (match.brand_id, match.pattern_id, match.confidence)

        if before == after:
            counters["unchanged"] += 1
            continue

        if before == (None, None, None):
            counters["filled"] += 1
        elif after == (None, None, None):
            counters["cleared"] += 1
        else:
            counters["updated"] += 1

        row.normalized_data_json = nd
        db.add(row)

    return dict(counters)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, default=None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)

    from app.core.db import SessionLocal

    with SessionLocal() as db:
        stats = backfill(db, user_id=args.user_id)
        if args.execute:
            db.commit()
            mode_label = "EXECUTED"
        else:
            db.rollback()
            mode_label = "DRY-RUN"
        logger.info(
            "%s. filled=%d updated=%d cleared=%d unchanged=%d "
            "skipped_no_skeleton=%d skipped_user_decision=%d",
            mode_label,
            stats.get("filled", 0),
            stats.get("updated", 0),
            stats.get("cleared", 0),
            stats.get("unchanged", 0),
            stats.get("skipped_no_skeleton", 0),
            stats.get("skipped_user_decision", 0),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
