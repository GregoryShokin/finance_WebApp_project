"""add_budget_alerts_table

Revision ID: 0018
Revises: fa6536b728c8
Create Date: 2026-03-30

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0018'
down_revision: Union[str, None] = 'fa6536b728c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'budget_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('alert_type', sa.String(length=32), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(length=1000), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default='false', nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_budget_alerts_id'), 'budget_alerts', ['id'], unique=False)
    op.create_index(op.f('ix_budget_alerts_user_id'), 'budget_alerts', ['user_id'], unique=False)
    op.create_index(op.f('ix_budget_alerts_alert_type'), 'budget_alerts', ['alert_type'], unique=False)
    op.create_index(op.f('ix_budget_alerts_category_id'), 'budget_alerts', ['category_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_budget_alerts_category_id'), table_name='budget_alerts')
    op.drop_index(op.f('ix_budget_alerts_alert_type'), table_name='budget_alerts')
    op.drop_index(op.f('ix_budget_alerts_user_id'), table_name='budget_alerts')
    op.drop_index(op.f('ix_budget_alerts_id'), table_name='budget_alerts')
    op.drop_table('budget_alerts')
