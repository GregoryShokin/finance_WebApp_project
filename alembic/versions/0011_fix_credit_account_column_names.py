"""fix credit account column names compatibility

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "credit_limit_original" not in account_columns:
        op.add_column("accounts", sa.Column("credit_limit_original", sa.Numeric(14, 2), nullable=True))

    if "credit_interest_rate" not in account_columns:
        op.add_column("accounts", sa.Column("credit_interest_rate", sa.Numeric(8, 3), nullable=True))

    if "credit_current_amount" not in account_columns:
        op.add_column("accounts", sa.Column("credit_current_amount", sa.Numeric(14, 2), nullable=True))
        if "credit_balance_current" in account_columns:
            op.execute(
                "UPDATE accounts SET credit_current_amount = credit_balance_current "
                "WHERE credit_current_amount IS NULL AND credit_balance_current IS NOT NULL"
            )

    if "credit_term_remaining" not in account_columns:
        op.add_column("accounts", sa.Column("credit_term_remaining", sa.Integer(), nullable=True))
        if "credit_remaining_term_months" in account_columns:
            op.execute(
                "UPDATE accounts SET credit_term_remaining = credit_remaining_term_months "
                "WHERE credit_term_remaining IS NULL AND credit_remaining_term_months IS NOT NULL"
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {column["name"] for column in inspector.get_columns("accounts")}

    for name in ["credit_term_remaining", "credit_current_amount"]:
        if name in account_columns:
            op.drop_column("accounts", name)
