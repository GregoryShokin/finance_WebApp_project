"""add deposit account fields

Revision ID: 0029_deposit_account_fields
Revises: 0028_stmt_account
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_deposit_account_fields"
down_revision = "0028_stmt_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("deposit_interest_rate", sa.Numeric(8, 3), nullable=True))
    op.add_column("accounts", sa.Column("deposit_open_date", sa.Date(), nullable=True))
    op.add_column("accounts", sa.Column("deposit_close_date", sa.Date(), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("deposit_capitalization", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("accounts", "deposit_capitalization")
    op.drop_column("accounts", "deposit_close_date")
    op.drop_column("accounts", "deposit_open_date")
    op.drop_column("accounts", "deposit_interest_rate")
