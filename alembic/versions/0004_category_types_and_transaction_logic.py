"""category types and transaction logic

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "categories",
        "priority",
        existing_type=sa.String(length=32),
        server_default="expense_essential",
        existing_nullable=False,
    )
    op.execute("UPDATE categories SET priority = 'expense_essential' WHERE priority = 'primary'")
    op.execute("UPDATE categories SET priority = 'expense_secondary' WHERE priority = 'secondary'")

    op.add_column(
        "transactions",
        sa.Column("operation_type", sa.String(length=32), nullable=False, server_default="regular"),
    )
    op.add_column(
        "transactions",
        sa.Column("affects_analytics", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_transactions_operation_type", "transactions", ["operation_type"], unique=False)
    op.create_index("ix_transactions_affects_analytics", "transactions", ["affects_analytics"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transactions_affects_analytics", table_name="transactions")
    op.drop_index("ix_transactions_operation_type", table_name="transactions")
    op.drop_column("transactions", "affects_analytics")
    op.drop_column("transactions", "operation_type")
    op.alter_column(
        "categories",
        "priority",
        existing_type=sa.String(length=32),
        server_default="primary",
        existing_nullable=False,
    )
    op.execute("UPDATE categories SET priority = 'primary' WHERE priority = 'expense_essential'")
    op.execute("UPDATE categories SET priority = 'secondary' WHERE priority = 'expense_secondary'")
