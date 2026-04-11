"""add telegram fields to users

Revision ID: 0031_telegram_users
Revises: 0030_deposit_cap_period
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_telegram_users"
down_revision = "0030_deposit_cap_period"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("telegram_username", sa.String(length=255), nullable=True))
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_id")
