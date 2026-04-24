"""Promote rule.confirms/rejections from Integer to Numeric(8,2) (§10.2 weighting)

Revision ID: 0053
Revises: 0052
Create Date: 2026-04-25

Why: The import spec (§10.2) weighs confirmations by the committing row's
status — `ready` counts as +1.0 while `warning` (bulk-ack) counts as +0.5.
Keeping the counter as Integer forced a binary confirm/no-confirm signal
that conflated evidence strength. Switching to Numeric(8, 2) preserves the
existing data (integer values cast losslessly) while making fractional
deltas natural. `rejections` follows for symmetry — current semantics are
integer-only, but future refinements (partial disagreement) benefit from
the same room to grow.

Thresholds in `Settings` (RULE_ACTIVATE_CONFIRMS, RULE_GENERALIZE_CONFIRMS,
RULE_DEACTIVATE_REJECTIONS) remain integer-typed in Python — the runtime
comparison against Numeric is compatible because SQLAlchemy casts under
the hood.
"""
from alembic import op
import sqlalchemy as sa


revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transaction_category_rules") as batch:
        batch.alter_column(
            "confirms",
            existing_type=sa.Integer(),
            type_=sa.Numeric(8, 2),
            existing_nullable=False,
            existing_server_default="1",
            server_default="1.00",
        )
        batch.alter_column(
            "rejections",
            existing_type=sa.Integer(),
            type_=sa.Numeric(8, 2),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0.00",
        )


def downgrade() -> None:
    with op.batch_alter_table("transaction_category_rules") as batch:
        batch.alter_column(
            "rejections",
            existing_type=sa.Numeric(8, 2),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0.00",
            server_default="0",
        )
        batch.alter_column(
            "confirms",
            existing_type=sa.Numeric(8, 2),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default="1.00",
            server_default="1",
        )
