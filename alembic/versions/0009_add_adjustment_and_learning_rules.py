"""add adjustment op type and category learning rules

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-22 13:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transaction_category_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("normalized_description", sa.String(length=500), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "normalized_description", "category_id", name="uq_tx_cat_rule_user_desc_category"),
    )
    op.create_index(op.f("ix_transaction_category_rules_id"), "transaction_category_rules", ["id"], unique=False)
    op.create_index(op.f("ix_transaction_category_rules_user_id"), "transaction_category_rules", ["user_id"], unique=False)
    op.create_index(op.f("ix_transaction_category_rules_normalized_description"), "transaction_category_rules", ["normalized_description"], unique=False)
    op.create_index(op.f("ix_transaction_category_rules_category_id"), "transaction_category_rules", ["category_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_transaction_category_rules_category_id"), table_name="transaction_category_rules")
    op.drop_index(op.f("ix_transaction_category_rules_normalized_description"), table_name="transaction_category_rules")
    op.drop_index(op.f("ix_transaction_category_rules_user_id"), table_name="transaction_category_rules")
    op.drop_index(op.f("ix_transaction_category_rules_id"), table_name="transaction_category_rules")
    op.drop_table("transaction_category_rules")
