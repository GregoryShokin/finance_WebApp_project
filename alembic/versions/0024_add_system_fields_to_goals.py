"""add_system_fields_to_goals

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-03

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "goals",
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "goals",
        sa.Column("system_key", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_goals_system_key", "goals", ["system_key"])
    op.create_unique_constraint("uq_goals_user_id_system_key", "goals", ["user_id", "system_key"])


def downgrade() -> None:
    op.drop_constraint("uq_goals_user_id_system_key", "goals", type_="unique")
    op.drop_index("ix_goals_system_key", table_name="goals")
    op.drop_column("goals", "system_key")
    op.drop_column("goals", "is_system")