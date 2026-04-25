"""One-shot: promote orphan-transfer ImportRows from ready/warning → error.

Context: §12.1 / §5.2 v1.1 trigger 6 — a transfer with only one known
account is forbidden. Before the build_preview gate was added, such rows
could slip through with status='ready' or 'warning'. On commit they'd
create a half-transfer (regular-looking transaction with one account),
which breaks balance math.

This script walks `import_rows`, finds rows with:
  * status IN ('ready', 'warning'),
  * operation_type = 'transfer' (from normalized_data_json),
  * at least one of account_id / target_account_id is missing,
and promotes them to status='error' with a human-readable issue appended.

Rows already `committed` / `duplicate` / `excluded` / `parked` / `error`
are skipped — the bug window is the commitable subset only.

Usage:
    docker compose exec api python -m scripts.fix_orphan_transfers           # dry-run
    docker compose exec api python -m scripts.fix_orphan_transfers --execute # apply
    docker compose exec api python -m scripts.fix_orphan_transfers --session 221
"""
from __future__ import annotations

import argparse
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.import_row import ImportRow
from app.services.import_service import ImportService


SCANNED_STATUSES = ("ready", "warning")
MARKER_ISSUE = "Перевод определён, но один из счетов не распознан — закрыто автофиксом."


def _is_missing(value: Any) -> bool:
    return value in (None, "", 0)


def run(*, execute: bool, session_filter: int | None) -> None:
    with SessionLocal() as db:
        q = select(ImportRow).where(ImportRow.status.in_(SCANNED_STATUSES))
        if session_filter is not None:
            q = q.where(ImportRow.session_id == session_filter)

        total_scanned = 0
        matched = 0
        promoted = 0
        samples: list[tuple[int, int, str, Any, Any]] = []  # (id, session_id, status, account_id, target)

        for row in db.execute(q).scalars().yield_per(500):
            total_scanned += 1
            normalized: dict[str, Any] = (
                getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
            )
            if str(normalized.get("operation_type") or "") != "transfer":
                continue
            account_id = normalized.get("account_id")
            target_account_id = normalized.get("target_account_id")
            if not (_is_missing(account_id) or _is_missing(target_account_id)):
                continue

            matched += 1
            if len(samples) < 15:
                samples.append(
                    (row.id, row.session_id, row.status, account_id, target_account_id)
                )

            # Apply the same gate the preview path now uses. Helper is pure,
            # safe to invoke here to get the canonical issue message.
            new_status, new_issues = ImportService._gate_transfer_integrity(
                normalized=normalized,
                current_status=row.status,
                issues=list(getattr(row, "errors", None) or []),
            )
            if new_status == row.status:
                continue  # nothing to do (duplicate row, etc.)

            if execute:
                row.status = new_status
                # Persist the issue text in whatever field the ORM exposes.
                # error_message column stores a single string; append our
                # marker if there's existing text so we don't clobber.
                joined = " | ".join(new_issues) if new_issues else None
                if hasattr(row, "error_message") and joined:
                    existing = getattr(row, "error_message", None)
                    row.error_message = (
                        f"{existing} | {joined}" if existing and joined not in existing else joined
                    )
                db.add(row)
            promoted += 1

        if execute:
            db.commit()

        print(f"Scanned rows in {SCANNED_STATUSES}: {total_scanned}")
        print(f"  matched orphan transfers:    {matched}")
        print(f"  promoted to error:           {promoted}")
        if samples:
            print("\nSample rows:")
            for rid, sid, st, acc, tgt in samples:
                print(f"  row={rid:>6} session={sid:>4} status={st:>7} account_id={acc} target_account_id={tgt}")
        if not execute:
            print("\nDry-run. Pass --execute to persist.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--session", type=int, default=None, help="Limit to a single session id")
    args = parser.parse_args()
    run(execute=args.execute, session_filter=args.session)


if __name__ == "__main__":
    main()
