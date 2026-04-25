"""One-shot: deactivate all rules with deprecated scope (PR1, §6.1 + §11.3).

Context: §6.1 names two new rule scopes (`specific` per-identifier and
`general` per-skeleton). The old `bank` and `legacy_pattern` scopes are
deprecated. PR1 of the legacy-cleanup work makes the preview rule lookup
ignore them — but they still live in the table with `is_active=True` from
before the cleanup, which would be confusing. This script flips those
rows to `is_active=False`.

What we DO NOT do (intentionally):
  * No DELETE — §11.3: "правила в `inactive` не удаляются жёстко сразу,
    хранятся для возможного ревью". The cleanup of accumulated history
    is a manual / future task, not this script.
  * No scope rewrite — keeping `legacy_pattern` / `bank` visible makes
    it obvious in the UI/audit that these rows were deactivated as part
    of the deprecation, not via organic decay (rejections > confirms).
  * No counter reset — confirms history is preserved so future migrations
    can use it to seed `general` rules.

Usage:
    docker compose exec api python -m scripts.deactivate_legacy_rules           # dry-run
    docker compose exec api python -m scripts.deactivate_legacy_rules --execute # apply
    docker compose exec api python -m scripts.deactivate_legacy_rules --user 42 # scope to one user
"""
from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.transaction_category_rule import (
    LEGACY_RULE_SCOPES,
    TransactionCategoryRule,
)


def run(*, execute: bool, user_filter: int | None) -> None:
    with SessionLocal() as db:
        q = select(TransactionCategoryRule).where(
            TransactionCategoryRule.scope.in_(tuple(LEGACY_RULE_SCOPES)),
            TransactionCategoryRule.is_active.is_(True),
        )
        if user_filter is not None:
            q = q.where(TransactionCategoryRule.user_id == user_filter)

        scope_counter: Counter = Counter()
        affected = 0
        for rule in db.execute(q).scalars().yield_per(500):
            scope_counter[rule.scope] += 1
            affected += 1
            if execute:
                rule.is_active = False
                db.add(rule)

        if execute:
            db.commit()

        print(f"Active legacy rules in scope {sorted(LEGACY_RULE_SCOPES)}: {affected}")
        for scope, n in sorted(scope_counter.items()):
            print(f"  {scope:>16} → {n}")
        if not execute:
            print("\nDry-run. Pass --execute to deactivate.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry-run)")
    parser.add_argument("--user", type=int, default=None, help="Limit to a single user_id")
    args = parser.parse_args()
    run(execute=args.execute, user_filter=args.user)


if __name__ == "__main__":
    main()
