"""add deferred purchase fields to transactions

Revision ID: 0027_deferred_purchase_fields
Revises: 0026_monthly_payment
Create Date: 2026-04-11 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_deferred_purchase_fields"
down_revision = "0026_monthly_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_deferred_purchase: marks a large credit/installment purchase whose
    # analytics impact is spread across future loan payments instead of
    # landing in the analytics immediately.
    op.add_column(
        "transactions",
        sa.Column(
            "is_deferred_purchase",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # deferred_remaining_amount: tracks how much principal on a deferred purchase
    # has not yet been attributed to the expense analytics. Decremented with every
    # credit_payment that carries principal against this purchase.
    op.add_column(
        "transactions",
        sa.Column("deferred_remaining_amount", sa.Numeric(14, 2), nullable=True),
    )

    # is_large_purchase: marks a large purchase made from free (non-credit) funds.
    # Such transactions are shown in the "Large Purchases" section and excluded
    # from average monthly expense calculations.
    op.add_column(
        "transactions",
        sa.Column(
            "is_large_purchase",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # source_payment_id: for credit_principal_attribution and credit_interest
    # expense transactions that are auto-created when a credit_payment is
    # processed. Points back to the originating credit_payment transaction.
    op.add_column(
        "transactions",
        sa.Column(
            "source_payment_id",
            sa.Integer(),
            sa.ForeignKey("transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Partial index: quickly find active deferred purchases for a given account.
    op.create_index(
        "idx_transactions_deferred_active",
        "transactions",
        ["account_id", "is_deferred_purchase"],
        postgresql_where=sa.text("is_deferred_purchase = TRUE"),
    )

    op.create_index(
        "idx_transactions_source_payment",
        "transactions",
        ["source_payment_id"],
        postgresql_where=sa.text("source_payment_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_transactions_source_payment", table_name="transactions")
    op.drop_index("idx_transactions_deferred_active", table_name="transactions")
    op.drop_column("transactions", "source_payment_id")
    op.drop_column("transactions", "is_large_purchase")
    op.drop_column("transactions", "deferred_remaining_amount")
    op.drop_column("transactions", "is_deferred_purchase")
