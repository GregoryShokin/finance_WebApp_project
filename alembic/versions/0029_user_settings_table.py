"""add user_settings table

Revision ID: 0029_user_settings
Revises: 0028_attribution_and_goal_category
Create Date: 2026-04-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029_user_settings"
down_revision = "0028_attribution_and_goal_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Fraction of avg monthly expenses above which a purchase is
        # considered "large" and offered deferred accounting.
        # Default: 0.200 (20 %). Allowed range enforced in application: 0.05–0.50.
        sa.Column(
            "large_purchase_threshold_pct",
            sa.Numeric(4, 3),
            nullable=False,
            server_default="0.200",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
