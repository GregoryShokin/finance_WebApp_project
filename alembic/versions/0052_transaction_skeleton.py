"""add transactions.skeleton for skeleton-based deduplication (§8.1)

Revision ID: 0052
Revises: 0051
Create Date: 2026-04-25

Why: The import spec (§8.1) defines the deduplication key as
(account_id, booking_date, amount, skeleton). The current implementation
discriminates by `normalized_description` — the enrichment's cleaned text —
which is not the same as the v2 normalizer's `skeleton` (placeholder-rich
form like "магазин продукты <NUM>"). Two payments to different phone numbers
with identical surrounding text share the same skeleton (merchant is the
same), which is exactly the dedup signal §8.1 wants.

Stored on each Transaction at commit time so future imports can match
against it. Existing rows get NULL — backfill happens in a separate script
that recomputes the skeleton from (bank_code, description) using the v2
normalizer, so the DDL stays reversible independently of data.
"""
from alembic import op
import sqlalchemy as sa


revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("skeleton", sa.String(500), nullable=True),
    )
    op.create_index(
        "ix_transactions_dedup_key",
        "transactions",
        ["user_id", "account_id", "transaction_date", "amount", "skeleton"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_dedup_key", table_name="transactions")
    op.drop_column("transactions", "skeleton")
