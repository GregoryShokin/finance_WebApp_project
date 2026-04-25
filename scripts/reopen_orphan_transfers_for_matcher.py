"""One-shot: reopen previously-escalated orphan transfers from error → warning
so the cross-session matcher gets another chance to find their pairs.

Context: a previous bug-fix immediately escalated transfer rows without a
known target_account_id to status='error' on the preview pass. The
debounced TransferMatcherService skips error rows (its query filters
status IN (ready, warning)), so those rows could never be paired even
when the counter-side existed in another session.

The current code keeps them at `warning` during preview and lets the
matcher attempt; only post-matcher orphans get escalated to `error`. But
rows already escalated by the old code stayed stuck.

This script walks active (uncommitted) sessions and:
  1. Drops status='error' transfer rows whose target_account_id is None
     back to status='warning'.
  2. Strips the stale "Перевод определён, но …" issues so the moderator
     UI doesn't keep showing the old reason text from the earlier pass.
  3. Triggers a fresh `TransferMatcherService.match_transfers_for_user`
     run so the rows get a real second chance. The matcher's own post-run
     escalation will return them to `error` if it can't find pairs.

Usage:
    docker compose exec api python -m scripts.reopen_orphan_transfers_for_matcher           # dry-run
    docker compose exec api python -m scripts.reopen_orphan_transfers_for_matcher --execute # apply
    docker compose exec api python -m scripts.reopen_orphan_transfers_for_matcher --user 42
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.transfer_matcher_service import TransferMatcherService


_STALE_ISSUE_PREFIXES = (
    "Перевод определён",
    "Не удалось определить счёт из выписки",
)


def run(*, execute: bool, user_filter: int | None) -> None:
    with SessionLocal() as db:
        q = (
            select(ImportRow, ImportSession.user_id)
            .join(ImportSession, ImportSession.id == ImportRow.session_id)
            .where(
                ImportSession.status != "committed",
                ImportRow.status == "error",
            )
        )
        if user_filter is not None:
            q = q.where(ImportSession.user_id == user_filter)

        affected_users: set[int] = set()
        reopened = 0
        for row, owner_user_id in db.execute(q).all():
            nd = dict(row.normalized_data_json or {})
            if str(nd.get("operation_type") or "") != "transfer":
                continue
            if nd.get("target_account_id") not in (None, "", 0):
                continue

            existing = (row.error_message or "").split(" | ")
            kept = [
                m for m in existing
                if m and not any(m.startswith(p) for p in _STALE_ISSUE_PREFIXES)
            ]
            new_error = " | ".join(kept) or None

            reopened += 1
            affected_users.add(int(owner_user_id))
            if execute:
                row.status = "warning"
                row.error_message = new_error
                db.add(row)

        if execute:
            db.commit()
            for uid in affected_users:
                # Single synchronous run — same code path the debounced
                # Celery job uses. Post-run escalation puts truly orphan
                # rows back into `error` automatically.
                TransferMatcherService(db).match_transfers_for_user(user_id=uid)
            db.commit()

        print(f"orphan transfer rows in `error`: {reopened}")
        print(f"users to re-match:               {len(affected_users)}")
        if not execute:
            print("\nDry-run. Pass --execute to reopen + re-match.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply changes")
    parser.add_argument("--user", type=int, default=None, help="Limit to one user_id")
    args = parser.parse_args()
    run(execute=args.execute, user_filter=args.user)


if __name__ == "__main__":
    main()
