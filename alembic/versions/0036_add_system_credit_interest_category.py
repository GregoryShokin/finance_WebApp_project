"""add system credit interest category for all users

Revision ID: 0036_sys_credit_interest
Revises: 0035_ip_transaction
Create Date: 2026-04-19

Ref: financeapp-vault/01-Metrics/Поток.md — проценты по кредитам = regular expense
Decision 2026-04-19: credit_payment упразднён, проценты классифицируются как расход в этой категории.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "0036_sys_credit_interest"
down_revision = "0035_ip_transaction"
branch_labels = None
depends_on = None

CATEGORY_NAME = "Проценты по кредитам"


def upgrade() -> None:
    conn = op.get_bind()

    user_ids = conn.execute(text("SELECT id FROM users")).fetchall()

    for (user_id,) in user_ids:
        existing = conn.execute(
            text(
                "SELECT id FROM categories "
                "WHERE user_id = :uid AND is_system = true AND name = :name"
            ),
            {"uid": user_id, "name": CATEGORY_NAME},
        ).fetchone()
        if existing:
            continue

        conn.execute(
            text(
                "INSERT INTO categories "
                "(user_id, name, kind, priority, regularity, is_system, icon_name, color, "
                "exclude_from_planning, created_at, updated_at) "
                "VALUES (:uid, :name, 'expense', 'expense_essential', 'regular', true, "
                "'percent', '#94a3b8', false, now(), now())"
            ),
            {"uid": user_id, "name": CATEGORY_NAME},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "DELETE FROM categories "
            "WHERE is_system = true AND name = :name"
        ),
        {"name": CATEGORY_NAME},
    )
