"""One-shot: rebuild decisions for ImportRows that drifted from spec.

Two distinct migration sub-modes, both addressing rows that carry stale
decision-side fields the spec now considers invalid:

──────────────────────────────────────────────────────────────────────
MODE 1: orphans  (PR1, §4.3 + §6.5)
──────────────────────────────────────────────────────────────────────
After `deactivate_legacy_rules.py` flips deprecated `bank` /
`legacy_pattern` rules to `is_active=False`, every preview-generated
ImportRow whose `applied_rule_id` points at one of those rules is now
stale. Its decision fields (`applied_rule_id`, `applied_rule_category_id`,
`predicted_category_id`, `category_id`) were filled silently from a
rule that should never have applied.

Strategy:
  1. Drop decision-side fields. Leave facts.
  2. Re-run rule lookup via `category_rule_repo.get_best_rule` against
     the now-cleaned rule store.
  3. Set status to "warning" (never "ready" on this migration pass).
  4. Append a one-time issue marker.

──────────────────────────────────────────────────────────────────────
MODE 3: self-loop (§12.1 extended)
──────────────────────────────────────────────────────────────────────
Transfers stored with `account_id == target_account_id` are semantically
invalid — money cannot move from a single account to itself. This pattern
was observed in session 229: the normalizer rewrote `account_id` from
the session's account (23) to the one mentioned in the description (22),
and the matcher then "matched" the row to its own income side on the
same account, leaving both fields equal.

Strategy:
  1. Drop the bogus `target_account_id` (set to NULL).
  2. Escalate to `status='error'` per §5.2 v1.1 trigger 6 + the extended
     gate added in commit alongside this script.
  3. Append a humane issue.

──────────────────────────────────────────────────────────────────────
MODE 2: demoted (§12.1 + §5.2 v1.1 trigger 6)
──────────────────────────────────────────────────────────────────────
Before commit 567b497 the preview pipeline silently demoted a row whose
fingerprint looked like a transfer but had no resolved counter-account
to `operation_type='regular'` and left it at `status='ready'`. Such
rows still carry the marker «понижен до regular» in `error_message`.

Per §12.1 these rows are integrity errors: a transfer with one missing
account cannot become a valid regular expense. The fix:
  1. Restore `operation_type='transfer'` so the commit-time gate
     (`_gate_transfer_integrity` with final=True) actually fires.
  2. Drop the wrongly-attached `category_id` (it came from a transfer-
     scoped rule before the demotion).
  3. Escalate to `status='error'` per §5.2 v1.1 trigger 6.
  4. Append a humane issue (§5.2 user-facing reason).

Only rows in `status='ready'` are touched in this mode:
  * `duplicate` rows are terminal (§8.3) — they will never commit.
  * `warning` rows are already visible to the user.
  * `committed`/`excluded`/`parked` rows are out of scope.

──────────────────────────────────────────────────────────────────────
Spec compliance (both modes):
  * §3.2 forbids re-running normalization (facts: skeleton/tokens/
    fingerprint stay). We DO NOT touch facts here.
  * §4.3 explicitly allows transparent re-run of decisions when the
    underlying knowledge changes — that's exactly this scenario.
  * §1.2 honesty: a row built on a stale decision must not stay in
    `ready` silently.

Skipped rows (mode 1):
  * status='committed' / 'duplicate' / 'excluded' / 'parked' / 'error':
    they're terminal or out-of-scope — not on the commit path.
  * normalized_data without applied_rule_id: nothing was applied, so
    nothing to roll back.
  * applied_rule_id whose rule is still active in a non-legacy scope:
    the matching is still valid, leave it alone.

Usage:
    # both modes (default — dry-run)
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans
    # only orphans
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans --mode orphans
    # only demoted-transfers
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans --mode demoted
    # apply
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans --execute
    docker compose exec api python -m scripts.rebuild_decisions_for_orphans --session 229
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
DEMOTED_MARKER = "понижен до regular"
DEMOTED_RESTORE_ISSUE = (
    "Перевод без счёта получателя: восстановлен operation_type=transfer, "
    "укажи счёт назначения вручную (§12.1)."
)
SELF_LOOP_ISSUE = (
    "Перевод указан на тот же счёт, что и источник — укажи реальный "
    "счёт-получатель (§12.1)."
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


def _looks_like_demoted_transfer(row: ImportRow, normalized: dict[str, Any]) -> bool:
    """True iff this row carries the silent-demotion signature.

    Signature (all must hold):
      * `error_message` contains the demotion marker (§5.2 trace),
      * current `operation_type='regular'` (the demoted target),
      * `target_account_id` is missing (the original integrity violation).

    Status is checked by the caller (we restore only `ready` rows to avoid
    poking duplicate/warning rows the user already has visibility into).
    """
    err = (getattr(row, "error_message", None) or "")
    if DEMOTED_MARKER not in err:
        return False
    if str(normalized.get("operation_type") or "regular").lower() != "regular":
        return False
    tgt = normalized.get("target_account_id")
    if tgt not in (None, "", 0):
        return False
    return True


def _process_orphan_row(
    db,
    row: ImportRow,
    normalized: dict[str, Any],
    repo: TransactionCategoryRuleRepository,
    *,
    rule_orphan_cache: dict[int, bool],
) -> tuple[bool, dict[str, Any], str, list[str], bool]:
    """Returns (changed, new_normalized, new_status, new_errors, rematched)."""
    applied_rule_id = normalized.get("applied_rule_id")
    try:
        applied_rule_id_int = int(applied_rule_id) if applied_rule_id is not None else None
    except (TypeError, ValueError):
        applied_rule_id_int = None

    if not _is_orphaned_rule_id(db, applied_rule_id_int, cache=rule_orphan_cache):
        return False, normalized, row.status, [], False

    new_normalized = dict(normalized)
    for field in DECISION_FIELDS_TO_DROP:
        new_normalized.pop(field, None)
    new_normalized["category_id"] = None

    norm_desc = new_normalized.get("normalized_description") or ""
    user_id = None
    if normalized.get("session_user_id"):
        user_id = int(normalized["session_user_id"])
    else:
        session = db.get(ImportSession, row.session_id)
        user_id = session.user_id if session is not None else None

    rematched = False
    if user_id is not None and norm_desc:
        new_rule = repo.get_best_rule(user_id=user_id, normalized_description=norm_desc)
        if new_rule is not None:
            new_normalized["applied_rule_id"] = new_rule.id
            new_normalized["applied_rule_category_id"] = new_rule.category_id
            new_normalized["category_id"] = new_rule.category_id
            rematched = True

    new_errors = list(getattr(row, "errors", None) or [])
    if MIGRATION_ISSUE not in new_errors:
        new_errors.append(MIGRATION_ISSUE)
    return True, new_normalized, "warning", new_errors, rematched


def _looks_like_self_loop_transfer(row: ImportRow, normalized: dict[str, Any]) -> bool:
    """True iff this row is a transfer with source == target.

    Status is checked by the caller — restore only `ready` rows so we
    don't disturb terminal/visible ones.
    """
    if str(normalized.get("operation_type") or "").lower() != "transfer":
        return False
    acc = normalized.get("account_id")
    tgt = normalized.get("target_account_id")
    if acc in (None, "", 0) or tgt in (None, "", 0):
        return False
    try:
        return int(acc) == int(tgt)
    except (TypeError, ValueError):
        return False


def _process_self_loop_row(
    row: ImportRow,
    normalized: dict[str, Any],
) -> tuple[bool, dict[str, Any], str, list[str]]:
    """Drop the bogus target_account_id, escalate to error.

    Returns (changed, new_normalized, new_status, new_errors).
    """
    if row.status != "ready":
        return False, normalized, row.status, []
    if not _looks_like_self_loop_transfer(row, normalized):
        return False, normalized, row.status, []

    new_normalized = dict(normalized)
    new_normalized["target_account_id"] = None
    # Category was likely also bogus (transfers don't carry budget category).
    new_normalized["category_id"] = None
    new_errors = list(getattr(row, "errors", None) or [])
    if SELF_LOOP_ISSUE not in new_errors:
        new_errors.append(SELF_LOOP_ISSUE)
    return True, new_normalized, "error", new_errors


def _process_demoted_row(
    row: ImportRow,
    normalized: dict[str, Any],
) -> tuple[bool, dict[str, Any], str, list[str]]:
    """Restore a silently-demoted transfer to (op=transfer, status=error).

    Returns (changed, new_normalized, new_status, new_errors).
    """
    if row.status != "ready":
        return False, normalized, row.status, []
    if not _looks_like_demoted_transfer(row, normalized):
        return False, normalized, row.status, []

    new_normalized = dict(normalized)
    new_normalized["operation_type"] = "transfer"
    # The category was inherited from the transfer-scoped rule before the
    # demotion — it has no place on a restored transfer (transfers don't
    # carry a budget category in our schema). Clear it.
    new_normalized["category_id"] = None
    new_errors = list(getattr(row, "errors", None) or [])
    if DEMOTED_RESTORE_ISSUE not in new_errors:
        new_errors.append(DEMOTED_RESTORE_ISSUE)
    return True, new_normalized, "error", new_errors


def run(*, execute: bool, session_filter: int | None, mode: str) -> None:
    with SessionLocal() as db:
        rule_orphan_cache: dict[int, bool] = {}
        repo = TransactionCategoryRuleRepository(db)

        q = select(ImportRow).where(ImportRow.status.in_(SCANNED_STATUSES))
        if session_filter is not None:
            q = q.where(ImportRow.session_id == session_filter)

        scanned = 0
        orphan_cleared = 0
        orphan_rematched = 0
        orphan_unmatched = 0
        demoted_restored = 0
        self_loop_fixed = 0
        sessions_touched: set[int] = set()
        per_session_changes: Counter = Counter()

        do_orphans = mode in ("orphans", "all")
        do_demoted = mode in ("demoted", "all")
        do_self_loop = mode in ("self-loop", "all")

        for row in db.execute(q).scalars().yield_per(500):
            scanned += 1
            normalized: dict[str, Any] = (
                getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
            )

            changed = False
            new_normalized = normalized
            new_status = row.status
            new_errors: list[str] = list(getattr(row, "errors", None) or [])

            if do_orphans:
                ch, new_normalized, new_status, new_errors, rematched = _process_orphan_row(
                    db, row, normalized, repo, rule_orphan_cache=rule_orphan_cache
                )
                if ch:
                    changed = True
                    orphan_cleared += 1
                    if rematched:
                        orphan_rematched += 1
                    else:
                        orphan_unmatched += 1

            if do_demoted and not changed:
                # Don't double-process: orphan-mode already wrote a fresh blob
                # and may have flipped status away from `ready`.
                ch, new_normalized, new_status, new_errors = _process_demoted_row(
                    row, normalized
                )
                if ch:
                    changed = True
                    demoted_restored += 1

            if do_self_loop and not changed:
                ch, new_normalized, new_status, new_errors = _process_self_loop_row(
                    row, normalized
                )
                if ch:
                    changed = True
                    self_loop_fixed += 1

            if not changed:
                continue

            sessions_touched.add(row.session_id)
            per_session_changes[row.session_id] += 1

            if execute:
                row.normalized_data_json = new_normalized
                row.status = new_status
                if hasattr(row, "error_message"):
                    row.error_message = " | ".join(m for m in new_errors if m) or None
                db.add(row)

        if execute:
            db.commit()

        print(f"Mode: {mode}")
        print(f"Scanned rows in {SCANNED_STATUSES}: {scanned}")
        if do_orphans:
            print(f"  [orphans]  rolled back to warning:   {orphan_cleared}")
            print(f"             re-matched to a new rule: {orphan_rematched}")
            print(f"             no rule matched (manual): {orphan_unmatched}")
        if do_demoted:
            print(f"  [demoted]  restored to (transfer + error): {demoted_restored}")
        if do_self_loop:
            print(f"  [self-loop] tgt cleared + escalated to error: {self_loop_fixed}")
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
    parser.add_argument(
        "--mode",
        choices=("orphans", "demoted", "self-loop", "all"),
        default="all",
        help="Which migration sub-mode to run (default: all)",
    )
    args = parser.parse_args()
    run(execute=args.execute, session_filter=args.session, mode=args.mode)


if __name__ == "__main__":
    main()
