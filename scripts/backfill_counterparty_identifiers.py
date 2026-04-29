"""Backfill: populate counterparty_identifiers from existing counterparty_fingerprints.

Context: the CounterpartyFingerprint binding was keyed by the v2 fingerprint,
which bakes account_id + bank into its hash — so a binding created on one
statement (e.g. Tinkoff credit) does not resolve the same recipient on another
(e.g. Tinkoff debit). CounterpartyIdentifier solves this forward from the
moment it was introduced; this script ports existing bindings into the new
table retroactively so the user does not have to re-confirm each counterparty.

For each (user_id, fingerprint) row in counterparty_fingerprints we find one
ImportRow of that user with that fingerprint, pull tokens from its
normalized_data_json, pick the strongest identifier using the same priority
as the cluster service (contract > phone > iban > card), and upsert a
matching binding into counterparty_identifiers. Rows whose sample does not
carry a supported identifier are skipped — those bindings are skeleton-based
(brand) and stay in counterparty_fingerprints.

Existing identifier bindings are treated as user-authoritative and not
overwritten (we skip, we do not re-vote), so re-running the script is safe.

Usage:
    docker compose exec api python -m scripts.backfill_counterparty_identifiers           # dry-run
    docker compose exec api python -m scripts.backfill_counterparty_identifiers --execute # apply
    docker compose exec api python -m scripts.backfill_counterparty_identifiers --user 3  # one user
"""
from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from app.core.db import SessionLocal
from app.models.counterparty_fingerprint import CounterpartyFingerprint
from app.models.counterparty_identifier import CounterpartyIdentifier
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.counterparty_identifier_repository import (
    CounterpartyIdentifierRepository,
)
from app.services.counterparty_identifier_service import SUPPORTED_IDENTIFIER_KINDS


# Same priority the cluster service uses when picking the cluster-level
# identifier_key/identifier_value. Keep them in sync.
_IDENTIFIER_PRIORITY = ("contract", "phone", "iban", "card")


def _pick_identifier(tokens: dict[str, Any]) -> tuple[str, str] | None:
    for kind in _IDENTIFIER_PRIORITY:
        if kind not in SUPPORTED_IDENTIFIER_KINDS:
            continue
        value = tokens.get(kind)
        if value:
            return kind, str(value)
    return None


def _build_fingerprint_index(
    db, *, user_filter: int | None,
) -> dict[tuple[int, str], dict[str, Any]]:
    """One-shot scan of import_rows → `{(user_id, fingerprint): tokens}`.

    We can't use a JSON path in the WHERE clause — `normalized_data_json` is
    declared as generic `JSON`, which doesn't expose `->>` / `.astext` in
    SQLAlchemy. Loading rows and filtering in Python is simple and fast
    enough: the first tokens dict encountered for each (user, fingerprint)
    wins; duplicates are ignored.
    """
    index: dict[tuple[int, str], dict[str, Any]] = {}
    q = db.query(ImportRow, ImportSession.user_id).join(
        ImportSession, ImportRow.session_id == ImportSession.id
    )
    if user_filter is not None:
        q = q.filter(ImportSession.user_id == user_filter)
    for row, user_id in q.yield_per(2000):
        normalized = row.normalized_data_json or {}
        fp = normalized.get("fingerprint")
        if not fp:
            continue
        key = (user_id, fp)
        if key in index:
            continue
        tokens = normalized.get("tokens")
        if not isinstance(tokens, dict):
            continue
        index[key] = tokens
    return index


def run(*, execute: bool, user_filter: int | None) -> None:
    with SessionLocal() as db:
        q = db.query(CounterpartyFingerprint)
        if user_filter is not None:
            q = q.filter(CounterpartyFingerprint.user_id == user_filter)
        fp_bindings = q.order_by(
            CounterpartyFingerprint.user_id, CounterpartyFingerprint.id
        ).all()

        total = len(fp_bindings)
        no_row_sample = 0        # fingerprint never seen in ImportRow — orphan
        no_identifier = 0        # sample exists but carries no supported token
        already_bound = 0        # identifier binding already present — left alone
        created = 0              # new identifier binding written (or would be)
        by_kind: Counter[str] = Counter()
        samples: list[tuple[int, str, str, str, int]] = []  # (user, kind, value, fp, cp_id)

        repo = CounterpartyIdentifierRepository(db)

        print(f"Scanning import_rows to build fingerprint→tokens index...")
        index = _build_fingerprint_index(db, user_filter=user_filter)
        print(f"  indexed {len(index)} fingerprints with tokens")

        for binding in fp_bindings:
            tokens = index.get((binding.user_id, binding.fingerprint))
            if tokens is None:
                no_row_sample += 1
                continue
            picked = _pick_identifier(tokens)
            if picked is None:
                no_identifier += 1
                continue
            kind, value = picked

            existing = repo.get(
                user_id=binding.user_id,
                identifier_kind=kind,
                identifier_value=value,
            )
            if existing is not None:
                already_bound += 1
                continue

            if execute:
                new_row = CounterpartyIdentifier(
                    user_id=binding.user_id,
                    identifier_kind=kind,
                    identifier_value=value,
                    counterparty_id=binding.counterparty_id,
                    confirms=binding.confirms or 1,
                )
                db.add(new_row)
                db.flush()

            created += 1
            by_kind[kind] += 1
            if len(samples) < 20:
                samples.append(
                    (binding.user_id, kind, value, binding.fingerprint, binding.counterparty_id)
                )

        if execute:
            db.commit()

        print("=" * 72)
        print(f"counterparty_fingerprints scanned: {total}")
        print(f"  already had identifier binding : {already_bound}")
        print(f"  no ImportRow sample found      : {no_row_sample}")
        print(f"  no supported identifier in row : {no_identifier}")
        print(f"  {'created' if execute else 'would create'}               : {created}")
        if by_kind:
            print("  by kind:")
            for kind, count in sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0])):
                print(f"    {kind:<10} {count}")
        if samples:
            print("  samples:")
            for uid, kind, value, fp, cp in samples:
                print(f"    user={uid} {kind}={value} fp={fp} → cp={cp}")
        if not execute:
            print()
            print("Dry-run — no changes written. Re-run with --execute to apply.")
        print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually write identifier bindings (default is dry-run).",
    )
    parser.add_argument(
        "--user", type=int, default=None,
        help="Limit to a single user_id (default: all users).",
    )
    args = parser.parse_args()
    run(execute=args.execute, user_filter=args.user)
