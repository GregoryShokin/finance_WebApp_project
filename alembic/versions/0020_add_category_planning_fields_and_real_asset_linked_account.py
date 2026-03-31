"""add_category_planning_fields_and_real_asset_linked_account

Revision ID: 0020
Revises: 0019
Create Date: 2026-03-30

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0020'
down_revision: Union[str, None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('exclude_from_planning', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column(
        'categories',
        sa.Column('income_type', sa.String(length=16), nullable=True),
    )
    op.add_column(
        'real_assets',
        sa.Column('linked_account_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_real_assets_linked_account_id',
        'real_assets',
        'accounts',
        ['linked_account_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_real_assets_linked_account_id', 'real_assets', type_='foreignkey')
    op.drop_column('real_assets', 'linked_account_id')
    op.drop_column('categories', 'income_type')
    op.drop_column('categories', 'exclude_from_planning')
