"""add contract number to accounts

Revision ID: 0027_contract_number
Revises: 0026_monthly_payment
Create Date: 2026-04-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_contract_number"
down_revision = "0026_monthly_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("contract_number", sa.String(100), nullable=True))
    op.create_index("ix_accounts_contract_number", "accounts", ["contract_number"])


def downgrade() -> None:
    op.drop_index("ix_accounts_contract_number", table_name="accounts")
    op.drop_column("accounts", "contract_number")
