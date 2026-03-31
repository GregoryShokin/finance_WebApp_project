"""add_goal_id_to_transactions

Revision ID: 0023
Revises: 0022
Create Date: 2026-03-31

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "goal_id",
            sa.Integer(),
            sa.ForeignKey("goals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_transactions_goal_id", "transactions", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_transactions_goal_id", table_name="transactions")
    op.drop_column("transactions", "goal_id")
