"""add credit early repayment operation type

Revision ID: 0025_add_credit_early_repayment_operation_type
Revises: 0024_add_system_fields_to_goals
Create Date: 2026-04-04 17:20:00
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0025_add_credit_early_repayment_operation_type"
down_revision = "0024_add_system_fields_to_goals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # operation_type is stored as String; this migration documents support for
    # the new credit_early_repayment value.
    pass


def downgrade() -> None:
    pass
