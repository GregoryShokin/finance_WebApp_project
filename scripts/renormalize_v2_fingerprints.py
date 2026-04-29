"""One-shot: re-run v2 normalization over existing ImportRow.normalized_data_json
so rows written before `transfer_identifier` was wired into `fingerprint()`
pick up identifier-aware hashes.

Context: rows in sessions created before the transfer-aware fingerprint code
landed carry a single shared fingerprint for every "Внешний перевод по номеру
телефона" row, regardless of which phone it actually was. The row-level
tokens are fine — only the fingerprint field is stale. This script re-runs
`_apply_v2_normalization` on each row, replacing the stored fingerprint with
the identifier-aware one while leaving everything else untouched.

Usage:
    docker compose exec api python -m scripts.renormalize_v2_fingerprints           # dry-run
    docker compose exec api python -m scripts.renormalize_v2_fingerprints --execute # apply
    docker compose exec api python -m scripts.renormalize_v2_fingerprints --session 210
"""
from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from app.core.db import SessionLocal
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_service import ImportService


# Rows in these statuses already turned into Transactions — we must not mutate
# their fingerprint (rules were learned against the old value). Skip them.
SKIPPED_ROW_STATUSES = frozenset({"committed"})

# Sessions past this status either have no live rows or are historical —
# re-normalizing adds risk without benefit. Live sessions are those the UI
# can still revisit via the moderator.
LIVE_SESSION_STATUSES = frozenset({"uploaded", "analyzed", "preview_ready"})


def run(*, execute: bool, session_filter: int | None) -> None:
    with SessionLocal() as db:
        q = db.query(ImportSession)
        if session_filter is not None:
            q = q.filter(ImportSession.id == session_filter)
        else:
            q = q.filter(ImportSession.status.in_(LIVE_SESSION_STATUSES))
        sessions = q.order_by(ImportSession.id).all()

        total_rows = 0
        changed_rows = 0
        skipped_committed = 0
        skipped_no_v2 = 0
        per_session: dict[int, dict[str, int]] = {}
        changed_samples: list[tuple[int, int, str, str]] = []  # (session, row_id, old_fp, new_fp)

        for session in sessions:
            rows = db.query(ImportRow).filter(ImportRow.session_id == session.id).all()
            s_changed = 0
            s_skipped = 0
            for row in rows:
                total_rows += 1
                if (row.status or "").lower() in SKIPPED_ROW_STATUSES or row.created_transaction_id is not None:
                    skipped_committed += 1
                    s_skipped += 1
                    continue
                existing = dict(row.normalized_data_json or {})
                if existing.get("normalizer_version") != 2:
                    skipped_no_v2 += 1
                    s_skipped += 1
                    continue
                old_fp = existing.get("fingerprint")
                result = ImportService._apply_v2_normalization(
                    normalized=existing,
                    session=session,
                    fallback_account_id=session.account_id,
                    row_index=row.row_index,
                    bank_code_override=(session.mapping_json or {}).get("bank_code"),
                )
                new_fp = result.get("fingerprint")
                if new_fp != old_fp:
                    changed_rows += 1
                    s_changed += 1
                    if len(changed_samples) < 8:
                        changed_samples.append((session.id, row.id, str(old_fp), str(new_fp)))
                    if execute:
                        row.normalized_data_json = result
                        db.add(row)
            per_session[session.id] = {"changed": s_changed, "skipped": s_skipped, "total": len(rows)}

        print("=" * 60)
        print(f"Sessions inspected: {len(sessions)}")
        print(f"Rows inspected:     {total_rows}")
        print(f"Rows with new fp:   {changed_rows}")
        print(f"Rows skipped (committed/has_tx): {skipped_committed}")
        print(f"Rows skipped (no v2 payload):    {skipped_no_v2}")
        print("=" * 60)

        if per_session:
            print("Per-session breakdown:")
            for sid, stats in per_session.items():
                if stats["changed"] or stats["total"]:
                    print(f"  session {sid}: changed={stats['changed']} / total={stats['total']} (skipped={stats['skipped']})")
            print()

        if changed_samples:
            print("Sample changes (first 8):")
            for sid, rid, old_fp, new_fp in changed_samples:
                print(f"  session={sid} row={rid}: {old_fp} → {new_fp}")
            print()

        # Distribution of how many unique new fingerprints the changed rows split
        # into — gives a quick "did we actually diversify?" signal per session.
        print("Fingerprint diversity check (new unique fps per session among changed rows):")
        by_session_new_fps: dict[int, Counter] = {}
        # Re-walk only to compute diversity cheaply; tiny cost vs. the main pass.
        for session in sessions:
            rows = db.query(ImportRow).filter(ImportRow.session_id == session.id).all()
            c: Counter = Counter()
            for row in rows:
                if (row.status or "").lower() in SKIPPED_ROW_STATUSES or row.created_transaction_id is not None:
                    continue
                existing = dict(row.normalized_data_json or {})
                if existing.get("normalizer_version") != 2:
                    continue
                result = ImportService._apply_v2_normalization(
                    normalized=existing,
                    session=session,
                    fallback_account_id=session.account_id,
                    row_index=row.row_index,
                    bank_code_override=(session.mapping_json or {}).get("bank_code"),
                )
                c[result.get("fingerprint")] += 1
            by_session_new_fps[session.id] = c
            print(f"  session {session.id}: {len(c)} unique fingerprints across {sum(c.values())} v2 rows")

        if execute:
            db.commit()
            print("\nCOMMITTED.")
        else:
            print("\nDry-run. Re-run with --execute to persist.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="persist changes (default: dry-run)")
    parser.add_argument("--session", type=int, default=None, help="limit to one session id")
    args = parser.parse_args()
    run(execute=args.execute, session_filter=args.session)
