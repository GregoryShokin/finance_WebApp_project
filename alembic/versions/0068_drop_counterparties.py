"""Drop counterparties + counterparty_fingerprints + counterparty_identifiers
+ transactions.counterparty_id (Phase C step 5 — destructive).

Revision ID: 0068
Revises: 0067
Create Date: 2026-05-08

This is the point of no return for the Phase C Brand merge. After this
revision runs, the legacy Counterparty schema is gone and only a pg_dump
restore can bring it back.

Sequence inside upgrade():

  1. Pre-flight tripwire. Aborts the upgrade BEFORE touching any schema
     if the dual-write window left any Transaction row with a
     `counterparty_id` set but no matching `brand_id`. That state would
     mean some write site we missed in step 4 is still emitting CP
     stamps without brand-side mirrors — dropping the column would
     silently lose the merchant link for those rows.

  2. Drop FK-bearing tables in dependency order:
        counterparty_fingerprints  (FKs counterparties)
        counterparty_identifiers   (FKs counterparties)
     followed by `counterparties` itself.

  3. DROP COLUMN transactions.counterparty_id and its index. Postgres
     auto-drops indices when the underlying column is dropped, but we
     drop it explicitly first for clarity in the migration log.

Downgrade is intentionally not implemented: a schema-only reverse
without the data move would leave the brand-side stores ahead of the CP
side and corrupt every read that joins through Counterparty. Recovery
path is documented in the docstring and in CLAUDE.md (Phase C history
section): restore from `backup_before_step5_*.sql` taken before this
migration ran.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0068"
down_revision: Union[str, None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tripwire: max number of rows we'll list in the abort message before
# truncating. Keep small — the alert is meant to surface the issue, not
# dump every offending row.
_TRIPWIRE_PREVIEW_LIMIT = 10


def _preflight_no_orphan_cp_stamps(conn) -> None:
    """Raise RuntimeError if any Transaction row carries a counterparty_id
    without the corresponding brand_id stamp. Such a row would lose its
    merchant link the moment the column drops below.

    The dual-write window in steps 2-3 backfilled brand_id for every row
    that had counterparty_id; step 4 stopped writing CP entirely. So a
    surviving CP-only row signals an unaudited write site, not a normal
    legacy state.
    """
    rows = conn.execute(sa.text(
        """
        SELECT id, user_id, counterparty_id, transaction_date
        FROM transactions
        WHERE counterparty_id IS NOT NULL
              AND brand_id IS NULL
        ORDER BY id ASC
        LIMIT :lim
        """
    ), {"lim": _TRIPWIRE_PREVIEW_LIMIT + 1}).fetchall()
    if not rows:
        return

    total = conn.execute(sa.text(
        """
        SELECT COUNT(*)
        FROM transactions
        WHERE counterparty_id IS NOT NULL AND brand_id IS NULL
        """
    )).scalar_one()

    preview = "\n".join(
        f"  tx_id={r.id} user_id={r.user_id} counterparty_id={r.counterparty_id} "
        f"transaction_date={r.transaction_date}"
        for r in rows[:_TRIPWIRE_PREVIEW_LIMIT]
    )
    raise RuntimeError(
        "Phase C step 5 pre-flight failed: "
        f"{total} Transaction row(s) carry counterparty_id without brand_id. "
        "Dropping transactions.counterparty_id now would lose the merchant "
        "link on those rows. Investigate the source — likely a write site "
        "missed during step 4 — backfill brand_id, then re-run.\n"
        f"First {min(total, _TRIPWIRE_PREVIEW_LIMIT)} offending rows:\n{preview}",
    )


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Tripwire — abort before any schema change if step 4 left
    #    inconsistent dual-write state.
    _preflight_no_orphan_cp_stamps(conn)

    # 2. Drop FK-bearing tables in dependency order. Both tables FK on
    #    counterparties.id, so they go first. Their indices and FK
    #    constraints disappear with the tables.
    op.drop_table("counterparty_fingerprints")
    op.drop_table("counterparty_identifiers")

    # 3. transactions.counterparty_id — drop the index first for an
    #    explicit migration log entry, then the column itself. The FK
    #    `transactions.counterparty_id → counterparties.id` is dropped
    #    automatically when the column goes.
    op.drop_index("ix_transactions_counterparty_id", table_name="transactions")
    op.drop_column("transactions", "counterparty_id")

    # 4. Drop counterparties last — every inbound FK is gone now.
    op.drop_table("counterparties")


def downgrade() -> None:
    """NOT IMPLEMENTED — data loss is irrecoverable from schema alone.

    Recovery path: restore the `backup_before_step5_*.sql` produced
    before running this migration. A schema-only reverse would leave the
    brand-side stores ahead of the recreated counterparty side, breaking
    every read that joins through Counterparty.
    """
    raise NotImplementedError(
        "Phase C step 5 (0068) is one-way. Restore from "
        "`backup_before_step5_*.sql` if a rollback is needed.",
    )
