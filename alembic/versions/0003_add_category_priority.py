"""add category priority

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="primary"),
    )
    op.create_index("ix_categories_priority", "categories", ["priority"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_categories_priority", table_name="categories")
    op.drop_column("categories", "priority")
