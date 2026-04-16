"""add installment_card account type and installment_purchases table

Revision ID: 0034_installment_card
Revises: 0033_regularity
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0034_installment_card"
down_revision = "0033_regularity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create installment_purchases table
    op.create_table(
        "installment_purchases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("original_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("remaining_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("interest_rate", sa.Numeric(8, 3), nullable=False, server_default="0"),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="active",
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 2. Add converted_to_installment to transactions
    op.add_column(
        "transactions",
        sa.Column(
            "converted_to_installment",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "converted_to_installment")
    op.drop_table("installment_purchases")
