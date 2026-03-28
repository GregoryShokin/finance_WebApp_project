"""add account type and credit card support

Revision ID: 0012
Revises: 0011
Create Date: 2026-03-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("account_type", sa.String(length=32), nullable=False, server_default="regular"),
    )
    op.create_index("ix_accounts_account_type", "accounts", ["account_type"], unique=False)
    op.execute("UPDATE accounts SET account_type = 'credit' WHERE is_credit = true")


def downgrade() -> None:
    op.drop_index("ix_accounts_account_type", table_name="accounts")
    op.drop_column("accounts", "account_type")
