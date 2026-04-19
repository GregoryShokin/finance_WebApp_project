"""
Data migration: split credit_payment → expense (interest) + transfer (principal).

Decision 2026-04-19: credit_payment operation_type is abolished.
Ref: financeapp-vault/01-Metrics/Поток.md

Usage:
    # dry-run (default, no changes committed):
    docker compose exec api python -m scripts.migrate_credit_payments

    # execute (wraps everything in one DB transaction):
    docker compose exec api python -m scripts.migrate_credit_payments --execute
"""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


def run(execute: bool) -> None:
    # Import here so the module is loadable even without app context during testing.
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/financeapp",
    )
    engine = create_engine(db_url, future=True)
    Session = sessionmaker(bind=engine)

    with Session() as session:
        if execute:
            _run_execute(session)
        else:
            _run_dry(session)


def _backup(session) -> None:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    backup_path = Path(f"backup_transactions_before_migration_{today}.sql")

    if backup_path.exists():
        print(f"  Backup already exists: {backup_path} — skipping.")
        return

    # Try pg_dump first; fall back to Python-based CSV export.
    from sqlalchemy import text as _text
    print(f"  Creating backup → {backup_path}")
    try:
        db_url = session.bind.url
        result = subprocess.run(
            ["pg_dump", "-h", str(db_url.host or "db"), "-p", str(db_url.port or 5432),
             "-U", str(db_url.username or "postgres"),
             "-t", "transactions", "--data-only", str(db_url.database or "financeapp")],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            backup_path.write_text(result.stdout, encoding="utf-8")
            print(f"  Backup saved via pg_dump: {backup_path}")
            return
    except FileNotFoundError:
        pass

    # pg_dump not available — export as INSERT statements via SQLAlchemy
    rows = session.execute(_text("SELECT * FROM transactions ORDER BY id")).fetchall()
    cols = session.execute(_text("SELECT * FROM transactions LIMIT 0")).keys()
    col_names = list(cols)
    lines = [f"-- transactions backup {today}\n"]
    for row in rows:
        vals = ", ".join(
            "NULL" if v is None else f"'{str(v)}'" for v in row
        )
        lines.append(f"INSERT INTO transactions ({', '.join(col_names)}) VALUES ({vals});\n")
    backup_path.write_text("".join(lines), encoding="utf-8")
    print(f"  Backup saved via SQLAlchemy: {backup_path} ({len(rows)} rows)")


def _collect_credit_payments(session):
    rows = session.execute(
        """
        SELECT id, user_id, account_id, target_account_id, credit_account_id,
               amount, currency, description, transaction_date, affects_analytics,
               credit_principal_amount, credit_interest_amount
        FROM transactions
        WHERE operation_type = 'credit_payment'
        ORDER BY id
        """
    ).fetchall()
    return rows


def _run_dry(session) -> None:
    from sqlalchemy import text

    rows = session.execute(
        text(
            "SELECT id, user_id, amount, credit_principal_amount, credit_interest_amount "
            "FROM transactions WHERE operation_type = 'credit_payment' ORDER BY id"
        )
    ).fetchall()

    total = len(rows)
    can_split = 0
    skipped: list[int] = []

    print(f"\n[DRY-RUN] Found {total} credit_payment transactions")
    print("-" * 60)

    for row in rows:
        tx_id, user_id, amount, principal, interest = row
        amount_d = _to_decimal(amount)
        principal_d = _to_decimal(principal)
        interest_d = _to_decimal(interest)

        if principal_d is None or interest_d is None:
            print(f"  SKIP  id={tx_id}: missing principal/interest (p={principal}, i={interest})")
            skipped.append(tx_id)
            continue

        if abs((principal_d + interest_d) - amount_d) > Decimal("0.01"):
            print(f"  SKIP  id={tx_id}: principal+interest={principal_d+interest_d} != amount={amount_d}")
            skipped.append(tx_id)
            continue

        print(f"  OK    id={tx_id} user={user_id}: amount={amount_d}  →  "
              f"interest(expense)={interest_d}  +  principal(transfer)={principal_d}")
        can_split += 1

    print("-" * 60)
    print(f"  Total credit_payment:  {total}")
    print(f"  Will split:            {can_split}")
    print(f"  Will skip:             {len(skipped)}")
    if skipped:
        print(f"  Skipped IDs:           {skipped}")
    print("\nRun with --execute to apply changes.")


def _run_execute(session) -> None:
    from sqlalchemy import text

    _backup(session)

    rows = session.execute(
        text(
            "SELECT id, user_id, account_id, target_account_id, credit_account_id, "
            "amount, currency, description, transaction_date, affects_analytics, "
            "credit_principal_amount, credit_interest_amount "
            "FROM transactions WHERE operation_type = 'credit_payment' ORDER BY id"
        )
    ).fetchall()

    total = len(rows)
    success = 0
    skipped: list[int] = []
    created_pairs: list[tuple[int, int, int]] = []  # (original_id, interest_id, principal_id)

    print(f"\n[EXECUTE] Processing {total} credit_payment transactions...")

    try:
        for row in rows:
            (tx_id, user_id, account_id, target_account_id, credit_account_id,
             amount, currency, description, tx_date, affects_analytics,
             principal_raw, interest_raw) = row

            amount_d = _to_decimal(amount)
            principal_d = _to_decimal(principal_raw)
            interest_d = _to_decimal(interest_raw)

            if principal_d is None or interest_d is None:
                print(f"  SKIP id={tx_id}: missing principal/interest")
                skipped.append(tx_id)
                continue

            if abs((principal_d + interest_d) - amount_d) > Decimal("0.01"):
                print(f"  SKIP id={tx_id}: principal+interest mismatch")
                skipped.append(tx_id)
                continue

            # Resolve interest category for this user
            cat_row = session.execute(
                text(
                    "SELECT id FROM categories "
                    "WHERE user_id = :uid AND is_system = true AND name = 'Проценты по кредитам'"
                ),
                {"uid": user_id},
            ).fetchone()

            if cat_row is None:
                print(f"  SKIP id={tx_id}: no interest category for user={user_id}")
                skipped.append(tx_id)
                continue

            interest_category_id = cat_row[0]

            # Resolve credit_account_id — used as target for the principal transfer
            eff_credit_account_id = credit_account_id or target_account_id

            interest_desc = f"Проценты · {description or ''}".strip(" ·")
            principal_desc = f"Тело кредита · {description or ''}".strip(" ·")
            now_sql = text("now()")

            # 1. Insert interest expense
            interest_row = session.execute(
                text(
                    "INSERT INTO transactions "
                    "(user_id, account_id, credit_account_id, category_id, "
                    "amount, currency, type, operation_type, description, "
                    "transaction_date, is_regular, affects_analytics, "
                    "credit_principal_amount, credit_interest_amount, "
                    "created_at, updated_at) "
                    "VALUES (:uid, :acc, :cacc, :cat, :amt, :cur, 'expense', 'regular', :desc, "
                    ":tdate, true, :affects, NULL, NULL, now(), now()) "
                    "RETURNING id"
                ),
                {
                    "uid": user_id,
                    "acc": account_id,
                    "cacc": eff_credit_account_id,
                    "cat": interest_category_id,
                    "amt": str(interest_d),
                    "cur": currency,
                    "desc": interest_desc,
                    "tdate": tx_date,
                    "affects": affects_analytics,
                },
            ).fetchone()
            interest_id = interest_row[0]

            # 2. Insert principal transfer
            principal_row = session.execute(
                text(
                    "INSERT INTO transactions "
                    "(user_id, account_id, target_account_id, credit_account_id, "
                    "amount, currency, type, operation_type, description, "
                    "transaction_date, is_regular, affects_analytics, "
                    "credit_principal_amount, credit_interest_amount, "
                    "created_at, updated_at) "
                    "VALUES (:uid, :acc, :tacc, :cacc, :amt, :cur, 'expense', 'transfer', :desc, "
                    ":tdate, true, false, NULL, NULL, now(), now()) "
                    "RETURNING id"
                ),
                {
                    "uid": user_id,
                    "acc": account_id,
                    "tacc": eff_credit_account_id,
                    "cacc": eff_credit_account_id,
                    "amt": str(principal_d),
                    "cur": currency,
                    "desc": principal_desc,
                    "tdate": tx_date,
                    "affects": affects_analytics,
                },
            ).fetchone()
            principal_id = principal_row[0]

            # 3. Delete original
            session.execute(
                text("DELETE FROM transactions WHERE id = :id"),
                {"id": tx_id},
            )

            created_pairs.append((tx_id, interest_id, principal_id))
            success += 1
            print(f"  OK  id={tx_id} → interest_id={interest_id}, principal_id={principal_id}")

        session.commit()
        print("\n[EXECUTE] Committed successfully.")

    except Exception as exc:
        session.rollback()
        print(f"\n[EXECUTE] ERROR — rolled back: {exc}")
        raise

    # Final report
    print("\n" + "=" * 60)
    print("MIGRATION REPORT")
    print("=" * 60)
    print(f"  Total credit_payment processed : {total}")
    print(f"  Successfully split             : {success}")
    print(f"  Skipped (missing data)         : {len(skipped)}")
    if skipped:
        print(f"  Skipped IDs for manual review  : {skipped}")
    from sqlalchemy import text as _text2
    remaining = session.execute(
        _text2("SELECT COUNT(*) FROM transactions WHERE operation_type = 'credit_payment'")
    ).scalar()
    print(f"  Remaining credit_payment in DB : {remaining}")
    print("=" * 60)


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate credit_payment → expense(interest) + transfer(principal)"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Apply changes (default: dry-run only)",
    )
    args = parser.parse_args()
    run(execute=args.execute)
