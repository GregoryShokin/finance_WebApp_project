"""add transfer_pair_id to transactions

Revision ID: 0017
Revises: 0016
Create Date: 2026-03-29

"""
from alembic import op
import sqlalchemy as sa

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("transfer_pair_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_transactions_transfer_pair_id",
        "transactions",
        "transactions",
        ["transfer_pair_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_transactions_transfer_pair_id", "transactions", ["transfer_pair_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_transfer_pair_id", table_name="transactions")
    op.drop_constraint("fk_transactions_transfer_pair_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "transfer_pair_id")
