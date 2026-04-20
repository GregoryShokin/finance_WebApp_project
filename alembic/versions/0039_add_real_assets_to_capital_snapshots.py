"""add real_assets_amount to capital_snapshots and populate net_capital

Revision ID: 0039_real_assets_snap
Revises: 0038_capital_snapshots
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0039_real_assets_snap"
down_revision = "0038_capital_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "capital_snapshots",
        sa.Column(
            "real_assets_amount",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
    )

    op.execute(
        """
        UPDATE capital_snapshots cs
        SET real_assets_amount = COALESCE((
            SELECT SUM(ra.estimated_value)
            FROM real_assets ra
            WHERE ra.user_id = cs.user_id
        ), 0)
        """
    )

    op.execute(
        """
        UPDATE capital_snapshots
        SET net_capital = liquid_amount + deposit_amount + real_assets_amount - credit_debt
        """
    )

    op.alter_column(
        "capital_snapshots",
        "net_capital",
        existing_type=sa.Numeric(14, 2),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "capital_snapshots",
        "net_capital",
        existing_type=sa.Numeric(14, 2),
        nullable=True,
    )
    op.drop_column("capital_snapshots", "real_assets_amount")
