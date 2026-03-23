"""add refund operation type support

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "transactions",
        "operation_type",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        server_default="regular",
    )


def downgrade() -> None:
    op.alter_column(
        "transactions",
        "operation_type",
        existing_type=sa.String(length=32),
        existing_nullable=False,
        server_default="regular",
    )
