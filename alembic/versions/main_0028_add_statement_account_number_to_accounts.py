"""add statement_account_number to accounts

Revision ID: 0028_stmt_account
Revises: 0027_contract_number
Create Date: 2026-04-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_stmt_account"
down_revision = "0027_contract_number"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("statement_account_number", sa.String(length=100), nullable=True))
    op.create_index("ix_accounts_statement_account_number", "accounts", ["statement_account_number"])


def downgrade() -> None:
    op.drop_index("ix_accounts_statement_account_number", table_name="accounts")
    op.drop_column("accounts", "statement_account_number")
