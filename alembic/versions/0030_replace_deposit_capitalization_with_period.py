"""replace deposit capitalization with period

Revision ID: 0030_deposit_cap_period
Revises: 0029_deposit_account_fields
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_deposit_cap_period"
down_revision = "0029_deposit_account_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("accounts", "deposit_capitalization")
    op.add_column("accounts", sa.Column("deposit_capitalization_period", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "deposit_capitalization_period")
    op.add_column(
        "accounts",
        sa.Column("deposit_capitalization", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
