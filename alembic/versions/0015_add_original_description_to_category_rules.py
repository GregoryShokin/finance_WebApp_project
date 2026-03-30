"""add original_description to transaction_category_rules

Revision ID: 0015
Revises: 0014
Create Date: 2026-03-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transaction_category_rules",
        sa.Column("original_description", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transaction_category_rules", "original_description")
