"""One-shot: split the Counterparty table into two roles — merchants/services
(stay in `counterparties`) and debtors/creditors (move to `debt_partners`).

Why: `Counterparty` is currently used as both the "merchant" linked to a
cluster (Пятёрочка, Яндекс Такси) AND the "person" involved in a debt
("Паша", "Отец"). Mixing them pollutes the debt UI with merchants and the
moderator UI with people. This script migrates data to two dedicated tables.

What it does for each user:
  1. Collects all Counterparties ever referenced by at least one `debt`
     transaction (`operation_type='debt'` AND `counterparty_id=<cp.id>`).
  2. For each such Counterparty, creates a matching DebtPartner with the same
     name + opening balances + same user_id.
     - If a DebtPartner with that name already exists for the user, reuse it.
  3. Updates every debt transaction: sets `debt_partner_id` to the new
     partner, clears `counterparty_id` (since per the new invariant
     counterparty is not used on debt rows).
  4. If a Counterparty ONLY appears on debt rows (no regular / refund row
     references it), the Counterparty row itself is deleted — it has no
     remaining purpose. Counterparties referenced by any non-debt row are
     kept as-is: they continue to live in `counterparties` for clusters.
     - A Counterparty that appears in BOTH roles ("Арендодатель" used both
       as merchant-like receiver of rent AND as debtor) stays in
       `counterparties` AND gains a twin in `debt_partners`. They are
       intentionally separate objects.

Usage:
    docker compose exec api python -m scripts.split_counterparties_into_debt_partners           # dry-run
    docker compose exec api python -m scripts.split_counterparties_into_debt_partners --execute # apply
    docker compose exec api python -m scripts.split_counterparties_into_debt_partners --user 3  # one user

Safe to re-run: rows already migrated (debt rows with debt_partner_id set and
counterparty_id null) are skipped.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from app.core.db import SessionLocal
from app.models.counterparty import Counterparty
from app.models.debt_partner import DebtPartner
from app.models.transaction import Transaction


def _debt_rows_for_user(db, *, user_id: int) -> list[Transaction]:
    """All debt transactions whose counterparty_id still points at the old
    table. Once migrated their counterparty_id is nulled, so re-runs find none."""
    return (
        db.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.operation_type == "debt",
            Transaction.counterparty_id.isnot(None),
        )
        .all()
    )


def _all_rows_by_counterparty(
    db, *, user_id: int, counterparty_ids: Iterable[int],
) -> dict[int, list[Transaction]]:
    """Group all transactions (any operation_type) by counterparty_id.

    Needed to decide whether a Counterparty is "debt-only" (can be deleted
    after migration) or "mixed-role" (must stay in counterparties as the
    merchant side, while a twin goes into debt_partners for the debtor side).
    """
    cp_ids = list(counterparty_ids)
    if not cp_ids:
        return {}
    rows = (
        db.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.counterparty_id.in_(cp_ids),
        )
        .all()
    )
    by_cp: dict[int, list[Transaction]] = defaultdict(list)
    for tx in rows:
        by_cp[tx.counterparty_id].append(tx)
    return by_cp


def _user_ids(db, *, filter_user_id: int | None) -> list[int]:
    q = db.query(Transaction.user_id).distinct()
    if filter_user_id is not None:
        q = q.filter(Transaction.user_id == filter_user_id)
    return [row[0] for row in q.all()]


def run(*, execute: bool, user_filter: int | None) -> None:
    with SessionLocal() as db:
        user_ids = _user_ids(db, filter_user_id=user_filter)

        total_users = len(user_ids)
        total_debt_rows = 0
        created_partners = 0
        reused_partners = 0
        deleted_counterparties = 0
        kept_mixed = 0

        for uid in user_ids:
            debt_rows = _debt_rows_for_user(db, user_id=uid)
            if not debt_rows:
                continue

            # Counterparties touched by this user's debt rows.
            cp_ids = {tx.counterparty_id for tx in debt_rows if tx.counterparty_id}
            cps = (
                db.query(Counterparty)
                .filter(
                    Counterparty.user_id == uid,
                    Counterparty.id.in_(cp_ids),
                )
                .all()
            )
            cp_by_id = {cp.id: cp for cp in cps}

            rows_by_cp = _all_rows_by_counterparty(
                db, user_id=uid, counterparty_ids=cp_ids,
            )

            # Create (or reuse) DebtPartner for each debt-referenced Counterparty.
            partner_id_by_cp_id: dict[int, int] = {}
            for cp_id, cp in cp_by_id.items():
                existing = (
                    db.query(DebtPartner)
                    .filter(
                        DebtPartner.user_id == uid,
                        DebtPartner.name == cp.name,
                    )
                    .first()
                )
                if existing is not None:
                    partner_id_by_cp_id[cp_id] = existing.id
                    reused_partners += 1
                    continue

                if execute:
                    partner = DebtPartner(
                        user_id=uid,
                        name=cp.name,
                        opening_receivable_amount=Decimal(str(cp.opening_receivable_amount or 0)),
                        opening_payable_amount=Decimal(str(cp.opening_payable_amount or 0)),
                    )
                    db.add(partner)
                    db.flush()
                    partner_id_by_cp_id[cp_id] = partner.id
                else:
                    # Use negative IDs in dry-run to keep the map keyed.
                    partner_id_by_cp_id[cp_id] = -cp_id
                created_partners += 1

            # Re-point debt rows to the new partner and clear counterparty_id.
            for tx in debt_rows:
                total_debt_rows += 1
                new_partner_id = partner_id_by_cp_id.get(tx.counterparty_id)
                if new_partner_id is None:
                    # Should not happen — debt row's counterparty wasn't in our
                    # fetched set (deleted cp? stale FK?). Skip safely.
                    continue
                if execute:
                    tx.debt_partner_id = new_partner_id
                    tx.counterparty_id = None

            # Decide per-counterparty: delete if debt-only, keep if mixed.
            for cp_id, cp in cp_by_id.items():
                other_role_rows = [
                    tx for tx in rows_by_cp.get(cp_id, [])
                    if tx.operation_type != "debt"
                ]
                if other_role_rows:
                    kept_mixed += 1
                    continue
                # Debt-only Counterparty — no further purpose. Delete.
                if execute:
                    db.delete(cp)
                deleted_counterparties += 1

        if execute:
            db.commit()

        print("=" * 72)
        print(f"users scanned                : {total_users}")
        print(f"debt transactions migrated   : {total_debt_rows}")
        print(f"DebtPartners created         : {created_partners}")
        print(f"DebtPartners reused (pre-existing name match): {reused_partners}")
        print(f"Counterparties deleted (debt-only): {deleted_counterparties}")
        print(f"Counterparties kept (mixed role)  : {kept_mixed}")
        if not execute:
            print()
            print("Dry-run — no changes written. Re-run with --execute to apply.")
        print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually write changes (default is dry-run).",
    )
    parser.add_argument(
        "--user", type=int, default=None,
        help="Limit to a single user_id (default: all users).",
    )
    args = parser.parse_args()
    run(execute=args.execute, user_filter=args.user)
