"""Rename account_type values to new enum (regular→main, credit→loan, deposit→savings, cash→main)
and add new types: marketplace, currency.

Revision ID: 0054
Revises: 0053
Create Date: 2026-04-28

Why: task #5 of import backlog — Account type metadata with subtypes.
The old ad-hoc strings ('regular', 'credit', 'deposit', 'cash') are replaced
with an explicit enum:
  main / marketplace / loan / credit_card / installment_card / broker / savings / currency

broker was already a valid string but absent from the UI; it is kept as-is.
installment_card and credit_card are unchanged.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RENAMES = [
    ("regular", "main"),
    ("cash",    "main"),
    ("credit",  "loan"),
    ("deposit", "savings"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in _RENAMES:
        conn.execute(
            sa.text("UPDATE accounts SET account_type = :new WHERE account_type = :old"),
            {"new": new, "old": old},
        )
    # Update server_default so new rows get 'main' by default.
    op.alter_column(
        "accounts",
        "account_type",
        server_default="main",
        existing_type=sa.String(32),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "accounts",
        "account_type",
        server_default="regular",
        existing_type=sa.String(32),
        nullable=False,
    )
    # Reverse the renames (cash cannot be distinguished from regular after merge).
    for new, old in reversed(_RENAMES):
        if old == "cash":
            continue  # cash merged into main — can't reverse cleanly
        op.execute(
            sa.text("UPDATE accounts SET account_type = :old WHERE account_type = :new"),
            {"new": new, "old": old},
        )
