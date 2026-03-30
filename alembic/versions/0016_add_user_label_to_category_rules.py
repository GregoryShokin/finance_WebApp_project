"""add user_label to transaction_category_rules

Revision ID: 0016
Revises: 0015
Create Date: 2026-03-29 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transaction_category_rules",
        sa.Column("user_label", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transaction_category_rules", "user_label")
