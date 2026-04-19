"""Backfill capital snapshots for historical months.

Run once after Phase 3 deployment to populate trend graphs.

Usage:
    docker compose exec api python -m scripts.backfill_capital_snapshots
    docker compose exec api python -m scripts.backfill_capital_snapshots --user-id=1
    docker compose exec api python -m scripts.backfill_capital_snapshots --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

from datetime import date


def run(user_id: int | None, dry_run: bool) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # Import all models so SQLAlchemy can resolve relationships
    import app.models.user
    import app.models.account
    import app.models.category
    import app.models.transaction
    import app.models.budget
    import app.models.budget_alert
    import app.models.goal
    import app.models.counterparty
    import app.models.import_session
    import app.models.import_row
    import app.models.transaction_category_rule
    import app.models.capital_snapshot
    try:
        import app.models.real_asset
        import app.models.installment_purchase
    except Exception:
        pass
    from app.models.user import User
    from app.services.capital_snapshot_service import CapitalSnapshotService

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://Gregory:4frt667nzb9ki@db:5432/FinanceDataBase",
    )
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        service = CapitalSnapshotService(db)

        if user_id is not None:
            user_ids = [user_id]
        else:
            user_ids = [row[0] for row in db.query(User.id).all()]

        total_created = 0
        total_skipped = 0

        for uid in user_ids:
            months = service.months_needing_snapshots(uid)
            if not months:
                print(f"  user={uid}: no transactions found, skipping")
                continue

            print(f"  user={uid}: {len(months)} months ({months[0]} → {months[-1]})")
            for month in months:
                if dry_run:
                    print(f"    [DRY-RUN] would create snapshot for {month}")
                    total_created += 1
                else:
                    try:
                        service.create_snapshot_for_month(uid, month)
                        total_created += 1
                    except Exception as exc:
                        print(f"    ERROR month={month}: {exc}")
                        total_skipped += 1

            if not dry_run:
                db.commit()
                print(f"    committed {len(months)} snapshots")

        print(f"\nDone. created={total_created} skipped={total_skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill capital snapshots")
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()
    run(user_id=args.user_id, dry_run=args.dry_run)
