"""align capital_snapshots with dashboard: add broker, receivable, counterparty debt

Revision ID: 0040_snap_align_dash
Revises: 0039_real_assets_snap
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0040_snap_align_dash"
down_revision = "0039_real_assets_snap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "capital_snapshots",
        sa.Column("broker_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "capital_snapshots",
        sa.Column("receivable_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "capital_snapshots",
        sa.Column("counterparty_debt", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )

    # Existing snapshots were computed with the old (non-dashboard-aligned)
    # formula — drop them so they get lazily rebuilt on next read.
    op.execute("DELETE FROM capital_snapshots")


def downgrade() -> None:
    op.drop_column("capital_snapshots", "counterparty_debt")
    op.drop_column("capital_snapshots", "receivable_amount")
    op.drop_column("capital_snapshots", "broker_amount")
