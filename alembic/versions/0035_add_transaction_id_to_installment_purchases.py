"""add transaction_id FK to installment_purchases

Revision ID: 0035_ip_transaction
Revises: 0034_installment_card
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0035_ip_transaction"
down_revision = "0034_installment_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installment_purchases",
        sa.Column(
            "transaction_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("installment_purchases", "transaction_id")
