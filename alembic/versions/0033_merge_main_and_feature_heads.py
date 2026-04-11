"""merge main branch and feature branch heads

Revision ID: 0033_merge_heads
Revises: 0032_telegram_link_code, 0029_user_settings
Create Date: 2026-04-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0033_merge_heads"
down_revision = ("0032_telegram_link_code", "0029_user_settings")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
