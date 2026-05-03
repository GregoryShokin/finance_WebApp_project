"""Denormalize fingerprint onto Transaction (spec §13, v1.20).

Revision ID: 0058
Revises: 0057
Create Date: 2026-05-03

Why: history-based orphan-transfer hint (§5.2 v1.20) needs a fast lookup of
"how many committed transactions of this fingerprint did the user already
classify as transfer". Today fingerprint lives on `import_rows.normalized_data_json`
and must be reached through `created_transaction_id` join — workable but
adds JSON-traversal cost to every history query.

Backfill: copy fingerprint from each ImportRow into the Transaction it created.
Forward path: `CommitOrchestrator.commit_row` will populate the field at commit
time (separate code change).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("fingerprint", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_transactions_fingerprint",
        "transactions",
        ["fingerprint"],
    )

    # Backfill from import_rows.normalized_data_json -> 'fingerprint'.
    # Postgres-only; sqlite tests don't run migrations against this column.
    op.execute(
        """
        UPDATE transactions t
        SET fingerprint = ir.normalized_data_json ->> 'fingerprint'
        FROM import_rows ir
        WHERE ir.created_transaction_id = t.id
          AND (ir.normalized_data_json ->> 'fingerprint') IS NOT NULL
          AND t.fingerprint IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_fingerprint", table_name="transactions")
    op.drop_column("transactions", "fingerprint")
