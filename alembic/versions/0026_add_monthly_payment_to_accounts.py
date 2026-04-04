"""add monthly payment to accounts

Revision ID: 0026_monthly_payment
Revises: 0025_credit_early_repayment
Create Date: 2026-04-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_monthly_payment"
down_revision = "0025_credit_early_repayment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("monthly_payment", sa.Numeric(14, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "monthly_payment")
