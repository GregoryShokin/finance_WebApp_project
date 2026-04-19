"""add capital_snapshots table

Revision ID: 0038_capital_snapshots
Revises: 0037_rm_credit_payment
Create Date: 2026-04-19

Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §2.3
Phase 3 Block A.
"""

from alembic import op
import sqlalchemy as sa


revision = "0038_capital_snapshots"
down_revision = "0037_rm_credit_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capital_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("snapshot_month", sa.Date(), nullable=False, index=True),
        sa.Column("liquid_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("deposit_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("credit_debt", sa.Numeric(14, 2), nullable=False),
        sa.Column("capital", sa.Numeric(14, 2), nullable=False),
        sa.Column("net_capital", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "snapshot_month", name="uq_capital_snapshots_user_month"),
    )


def downgrade() -> None:
    op.drop_table("capital_snapshots")
