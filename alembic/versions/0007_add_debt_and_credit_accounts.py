"""add debt operation type and credit account flag

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    account_columns = {column["name"] for column in inspector.get_columns("accounts")}
    if "is_credit" not in account_columns:
        op.add_column(
            "accounts",
            sa.Column("is_credit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index(op.f("ix_accounts_is_credit"), "accounts", ["is_credit"], unique=False)

    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    if "operation_type" in transaction_columns:
        op.alter_column(
            "transactions",
            "operation_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=32),
            existing_nullable=False,
            existing_server_default="regular",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "is_credit" in account_columns:
        indexes = {index["name"] for index in inspector.get_indexes("accounts")}
        index_name = op.f("ix_accounts_is_credit")
        if index_name in indexes:
            op.drop_index(index_name, table_name="accounts")
        op.drop_column("accounts", "is_credit")
