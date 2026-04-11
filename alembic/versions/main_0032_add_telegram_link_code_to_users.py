"""add telegram link code fields to users

Revision ID: 0032_telegram_link_code
Revises: 0031_telegram_users
Create Date: 2026-04-07
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_telegram_link_code"
down_revision = "0031_telegram_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_link_code", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("telegram_link_code_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_telegram_link_code", "users", ["telegram_link_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_telegram_link_code", table_name="users")
    op.drop_column("users", "telegram_link_code_expires_at")
    op.drop_column("users", "telegram_link_code")