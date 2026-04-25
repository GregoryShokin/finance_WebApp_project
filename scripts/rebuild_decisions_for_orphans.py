"""One-shot: rebuild decisions for ImportRows that fed off a now-inactive rule.

Context (PR1, §4.3 + §6.5): after `deactivate_legacy_rules.py` flips
deprecated `bank` / `legacy_pattern` rules to `is_active=False`, every
preview-generated ImportRow whose `applied_rule_id` points at one of
those rules is now stale. Its decision fields (`applied_rule_id`,
`applied_rule_category_id`, `predicted_category_id`, `category_id`)
were filled silently from a rule that should never have applied.

Spec compliance:
  * §3.2 forbids re-running normalization (facts: skeleton/tokens/
    fingerprint stay). We DO NOT touch facts here.
  * §4.3 explicitly allows transparent re-run of decisions when the
    underlying knowledge changes — that's exactly this scenario.
  * §1.2 honesty: a row built on a deactivated rule must not stay in
    `ready` silently. We escalate to `warning` minimum so the user
    explicitly re-touches the row before commit. Re-matching may
    propose a NEW rule's prediction, but status still becomes `warning`
    — this is a one-time migration measure, not the normal path.

Strategy per affected row:
  1. Drop decision-side fields: applied_rule_id, applied_rule_category_id,
     predicted_category_id, predicted_counterparty_id, category_id.
     Leave facts (amount, date, raw_description, skeleton, tokens,
     fingerprint, direction, account_id, bank_code).
  2. Re-run rule lookup via `category_rule_repo.get_best_rule` against
     the now-cleaned rule store. The new lookup respects PR1 filters
     (is_active=True AND scope IN specific/general), so legacy rules
     no longer match.
  3. Set status to "warning" (never "ready" on this migration pass).
  4. Append a one-time issue marker so the user sees why.

Skipped rows:
  * status='committed' / 'duplicate' / 'excluded' / 'parked' / 'error':
    they're terminal or out-of-scope — not on the commit path.
  * normalized_data without applied_rule_id: nothing was applied, so
    nothing to roll back.
  * applied_rule_id whose rule is still active in a non-legacy scope:
    the matching is still valid, leave it alone.

Usage:
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans           # dry-run
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans --execute # apply
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans --session 221
"""
from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction_category_rule import TransactionCategoryRule
from app.repositories.transaction_category_rule_repository import (
    TransactionCategoryRuleRepository,
)


SCANNED_STATUSES = ("ready", "warning")
MIGRATION_ISSUE = (
    "Категория пересчитана: предыдущее правило отключено как устаревшее. "
    "Подтверди вручную."
)
DECISION_FIELDS_TO_DROP = (
    "applied_rule_id",
    "applied_rule_category_id",
    "predicted_category_id",
    "predicted_counterparty_id",
)


def _is_orphaned_rule_id(
    db, rule_id: int | None, *, cache: dict[int, bool]
) -> bool:
    """True iff `rule_id` points at a non-existent or now-inactive rule."""
    if rule_id is None:
        return False
    if rule_id in cache:
        return cache[rule_id]
    rule = db.get(TransactionCategoryRule, rule_id)
    orphaned = rule is None or rule.is_active is False
    cache[rule_id] = orphaned
    return orphaned


def run(*, execute: bool, session_filter: int | None) -> None:
    with SessionLocal() as db:
        rule_orphan_cache: dict[int, bool] = {}
        repo = TransactionCategoryRuleRepository(db)

        q = select(ImportRow).where(ImportRow.status.in_(SCANNED_STATUSES))
        if session_filter is not None:
            q = q.where(ImportRow.session_id == session_filter)

        scanned = 0
        cleared = 0
        rematched = 0
        unmatched = 0
        sessions_touched: set[int] = set()
        per_session_changes: Counter = Counter()

        for row in db.execute(q).scalars().yield_per(500):
            scanned += 1
            normalized: dict[str, Any] = (
                getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
            )
            applied_rule_id = normalized.get("applied_rule_id")
            try:
                applied_rule_id_int = int(applied_rule_id) if applied_rule_id is not None else None
            except (TypeError, ValueError):
                applied_rule_id_int = None

            if not _is_orphaned_rule_id(db, applied_rule_id_int, cache=rule_orphan_cache):
                continue

            cleared += 1
            sessions_touched.add(row.session_id)
            per_session_changes[row.session_id] += 1

            # Build a fresh normalized blob — drop decision fields, keep facts.
            new_normalized = dict(normalized)
            for field in DECISION_FIELDS_TO_DROP:
                new_normalized.pop(field, None)
            # category_id was the user-visible "predicted" category; clear it
            # too so the moderator UI doesn't pre-fill the wrong choice.
            new_normalized["category_id"] = None

            # Re-match against the cleaned rule store.
            norm_desc = new_normalized.get("normalized_description") or ""
            user_id = None
            if normalized.get("session_user_id"):
                user_id = int(normalized["session_user_id"])
            else:
                # Fall back to the session's user_id — needed for the lookup.
                session = db.get(ImportSession, row.session_id)
                user_id = session.user_id if session is not None else None

            new_rule = None
            if user_id is not None and norm_desc:
                new_rule = repo.get_best_rule(
                    user_id=user_id, normalized_description=norm_desc
                )

            if new_rule is not None:
                new_normalized["applied_rule_id"] = new_rule.id
                new_normalized["applied_rule_category_id"] = new_rule.category_id
                new_normalized["category_id"] = new_rule.category_id
                rematched += 1
            else:
                unmatched += 1

            # §1.2: even a fresh match must be re-touched by the user before
            # commit on this migration pass — escalate to warning.
            new_status = "warning"
            new_errors = list(getattr(row, "errors", None) or [])
            if MIGRATION_ISSUE not in new_errors:
                new_errors.append(MIGRATION_ISSUE)

            if execute:
                row.normalized_data_json = new_normalized
                row.status = new_status
                # error_message column stores a single string; concatenate.
                if hasattr(row, "error_message"):
                    row.error_message = " | ".join(
                        m for m in new_errors if m
                    ) or None
                db.add(row)

        if execute:
            db.commit()

        print(f"Scanned rows in {SCANNED_STATUSES}: {scanned}")
        print(f"  rolled back to warning:    {cleared}")
        print(f"  re-matched to a new rule:  {rematched}")
        print(f"  no rule matched (manual):  {unmatched}")
        print(f"  sessions touched:          {len(sessions_touched)}")
        if per_session_changes:
            top = per_session_changes.most_common(10)
            print("\nTop sessions by change count:")
            for sid, n in top:
                print(f"  session={sid} rows_changed={n}")
        if not execute:
            print("\nDry-run. Pass --execute to persist.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--session", type=int, default=None, help="Limit to one session id")
    args = parser.parse_args()
    run(execute=args.execute, session_filter=args.session)


if __name__ == "__main__":
    main()
