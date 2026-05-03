"""Add `is_closed` and `closed_at` to accounts (spec §13, v1.20).

Revision ID: 0057
Revises: 0056
Create Date: 2026-05-03

Why: a closed account is a first-class state — it stays in DB with all its
historical transactions, but is hidden from active lists. Imported orphan
transfers can have a closed account as their target, so the moderator's
account-selector must keep it visible. `is_active` already exists but its
semantic is "temporarily hidden", which doesn't carry the dated-closure
meaning needed for reconciliation and orphan-target binding.

Backfill rule: leave `is_closed=False` for all existing rows. We do NOT
auto-promote `is_active=False` to `is_closed=True` because the two flags
mean different things. Users explicitly mark closure via the UI.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column(
            "is_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "accounts",
        sa.Column(
            "closed_at",
            sa.Date(),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_accounts_is_closed",
        "accounts",
        ["is_closed"],
    )


def downgrade() -> None:
    op.drop_index("ix_accounts_is_closed", table_name="accounts")
    op.drop_column("accounts", "closed_at")
    op.drop_column("accounts", "is_closed")
