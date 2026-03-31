"""add_suggested_amount_to_budgets

Revision ID: 0021
Revises: 0020
Create Date: 2026-03-30

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "budgets",
        sa.Column(
            "suggested_amount",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("budgets", "suggested_amount")
