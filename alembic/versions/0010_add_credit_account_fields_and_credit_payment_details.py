"""add credit account fields and credit payment details

Revision ID: 0010
Revises: 0009_add_adjustment_and_learning_rules
Create Date: 2026-03-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("credit_limit_original", sa.Numeric(14, 2), nullable=True))
    op.add_column("accounts", sa.Column("credit_balance_current", sa.Numeric(14, 2), nullable=True))
    op.add_column("accounts", sa.Column("credit_interest_rate", sa.Numeric(7, 3), nullable=True))
    op.add_column("accounts", sa.Column("credit_remaining_term_months", sa.Integer(), nullable=True))

    op.add_column("transactions", sa.Column("credit_account_id", sa.Integer(), nullable=True))
    op.add_column("transactions", sa.Column("credit_principal_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("transactions", sa.Column("credit_interest_amount", sa.Numeric(14, 2), nullable=True))
    op.create_foreign_key(
        "fk_transactions_credit_account_id_accounts",
        "transactions",
        "accounts",
        ["credit_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_transactions_credit_account_id", "transactions", ["credit_account_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_transactions_credit_account_id", table_name="transactions")
    op.drop_constraint("fk_transactions_credit_account_id_accounts", "transactions", type_="foreignkey")
    op.drop_column("transactions", "credit_interest_amount")
    op.drop_column("transactions", "credit_principal_amount")
    op.drop_column("transactions", "credit_account_id")

    op.drop_column("accounts", "credit_remaining_term_months")
    op.drop_column("accounts", "credit_interest_rate")
    op.drop_column("accounts", "credit_balance_current")
    op.drop_column("accounts", "credit_limit_original")
