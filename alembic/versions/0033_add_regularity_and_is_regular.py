"""add regularity to categories and is_regular to transactions

Revision ID: 0033_regularity
Revises: 0032_telegram_link_code
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_regularity"
down_revision = "0032_telegram_link_code"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add regularity column to categories
    op.add_column(
        "categories",
        sa.Column(
            "regularity",
            sa.String(length=16),
            nullable=False,
            server_default="regular",
        ),
    )
    op.create_index("ix_categories_regularity", "categories", ["regularity"])

    # 2. Add is_regular column to transactions
    op.add_column(
        "transactions",
        sa.Column(
            "is_regular",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.create_index("ix_transactions_is_regular", "transactions", ["is_regular"])

    # 3. Backfill: categories with exclude_from_planning=True get regularity='irregular'
    op.execute(
        "UPDATE categories SET regularity = 'irregular' WHERE exclude_from_planning = true"
    )

    # 4. Backfill: transactions whose category has exclude_from_planning=True get is_regular=False
    op.execute(
        """
        UPDATE transactions
        SET is_regular = false
        WHERE category_id IN (
            SELECT id FROM categories WHERE exclude_from_planning = true
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_is_regular", table_name="transactions")
    op.drop_column("transactions", "is_regular")
    op.drop_index("ix_categories_regularity", table_name="categories")
    op.drop_column("categories", "regularity")
