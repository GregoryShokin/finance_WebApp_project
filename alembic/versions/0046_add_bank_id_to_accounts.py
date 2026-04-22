"""add bank_id to accounts

Revision ID: 0046
Revises: 0045
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("bank_id", sa.Integer(), sa.ForeignKey("banks.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_accounts_bank_id", "accounts", ["bank_id"])


def downgrade() -> None:
    op.drop_index("ix_accounts_bank_id", "accounts")
    op.drop_column("accounts", "bank_id")
