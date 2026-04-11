"""add credit_principal_attribution operation type and goal category_id

Revision ID: 0028_attribution_and_goal_category
Revises: 0027_deferred_purchase_fields
Create Date: 2026-04-11 00:00:00.000000

Notes:
  - operation_type is stored as VARCHAR(32), not a PostgreSQL enum, so no
    ALTER TYPE is required. The new value 'credit_principal_attribution' is
    simply documented here and handled in application code.
  - goal.category_id links a purchase goal to its expense category so that
    contributions to that goal are recorded under the matching category in
    the analytics pie chart.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028_attribution_and_goal_category"
down_revision = "0027_deferred_purchase_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # operation_type is VARCHAR — no DDL change needed for the new value.
    # This migration exists as a documentation checkpoint.

    op.add_column(
        "goals",
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("goals", "category_id")
