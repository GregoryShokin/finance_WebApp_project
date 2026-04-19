"""remove credit_payment and credit_interest from TransactionOperationType enum

Revision ID: 0037_rm_credit_payment
Revises: 0036_sys_credit_interest
Create Date: 2026-04-19

IMPORTANT: Run scripts/migrate_credit_payments.py --execute BEFORE applying this migration.
The upgrade() will ABORT if any credit_payment rows remain.

Ref: financeapp-vault/01-Metrics/Поток.md — decision 2026-04-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0037_rm_credit_payment"
down_revision = "0036_sys_credit_interest"
branch_labels = None
depends_on = None

_OLD_ENUM_VALUES = (
    "regular", "transfer", "investment_buy", "investment_sell",
    "credit_disbursement", "credit_payment", "credit_early_repayment",
    "credit_interest", "debt", "refund", "adjustment",
)

_NEW_ENUM_VALUES = (
    "regular", "transfer", "investment_buy", "investment_sell",
    "credit_disbursement", "credit_early_repayment",
    "debt", "refund", "adjustment",
)


def upgrade() -> None:
    conn = op.get_bind()

    # Safety check — abort if any credit_payment rows remain
    remaining = conn.execute(
        text("SELECT COUNT(*) FROM transactions WHERE operation_type IN ('credit_payment', 'credit_interest')")
    ).scalar()
    if remaining and remaining > 0:
        raise RuntimeError(
            f"Cannot remove credit_payment/credit_interest from enum: "
            f"{remaining} transaction(s) still use these values. "
            "Run: docker compose exec api python -m scripts.migrate_credit_payments --execute"
        )

    # PostgreSQL enum migration: create new type, alter column, drop old type.
    # The column is String(32) — no actual enum type in DB, just string values.
    # So we only need to verify no rows use the old values (done above).
    # No DDL change needed for the column itself.
    #
    # If the project ever switches to a native PostgreSQL ENUM type, replace this
    # section with CREATE TYPE / ALTER COLUMN / DROP TYPE statements.
    pass


def downgrade() -> None:
    # Values were strings — downgrade is a no-op at the DB level.
    # The application code is responsible for re-accepting credit_payment values.
    pass
