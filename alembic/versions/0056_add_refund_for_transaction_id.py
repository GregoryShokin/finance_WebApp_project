"""Add refund_for_transaction_id to transactions.

Revision ID: 0056
Revises: 0055
Create Date: 2026-05-02

Why: refund→original purchase link was previously stored only in
ImportRow.normalized_data_json["refund_match"] and lost on commit.
This column persists the link on the Transaction itself so analytics,
UI history, and future re-imports can resolve the original purchase
without touching import data.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "refund_for_transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "refund_for_transaction_id")
