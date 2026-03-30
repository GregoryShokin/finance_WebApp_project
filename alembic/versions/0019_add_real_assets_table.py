"""add_real_assets_table

Revision ID: 0019
Revises: 0018
Create Date: 2026-03-30

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0019'
down_revision: Union[str, None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'real_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('asset_type', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('estimated_value', sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_real_assets_id'), 'real_assets', ['id'], unique=False)
    op.create_index(op.f('ix_real_assets_user_id'), 'real_assets', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_real_assets_user_id'), table_name='real_assets')
    op.drop_index(op.f('ix_real_assets_id'), table_name='real_assets')
    op.drop_table('real_assets')
