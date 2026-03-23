"""add target account to transactions

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("target_account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_transactions_target_account_id", "transactions", ["target_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transactions_target_account_id", table_name="transactions")
    op.drop_column("transactions", "target_account_id")
