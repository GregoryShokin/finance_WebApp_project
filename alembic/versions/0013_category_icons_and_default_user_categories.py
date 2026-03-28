"""category icons and default user categories

Revision ID: 0013
Revises: 0012
Create Date: 2026-03-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ICON_BY_NAME = {
    'Жильё': 'house',
    'Продукты': 'shopping-basket',
    'Транспорт': 'car',
    'Связь и интернет': 'smartphone',
    'Здоровье': 'heart-pulse',
    'Образование': 'book-open',
    'Кафе и рестораны': 'utensils-crossed',
    'Маркетплейсы': 'shopping-bag',
    'Одежда': 'shirt',
    'Развлечения': 'clapperboard',
    'Путешествия': 'plane',
    'Подарки': 'gift',
    'Красота и уход': 'sparkles',
    'Животные': 'paw-print',
}

DEFAULT_CATEGORIES = [
    ('Жильё', 'expense', 'expense_essential', 'house'),
    ('Продукты', 'expense', 'expense_essential', 'shopping-basket'),
    ('Транспорт', 'expense', 'expense_essential', 'car'),
    ('Связь и интернет', 'expense', 'expense_essential', 'smartphone'),
    ('Здоровье', 'expense', 'expense_essential', 'heart-pulse'),
    ('Образование', 'expense', 'expense_essential', 'book-open'),
    ('Кафе и рестораны', 'expense', 'expense_secondary', 'utensils-crossed'),
    ('Маркетплейсы', 'expense', 'expense_secondary', 'shopping-bag'),
    ('Одежда', 'expense', 'expense_secondary', 'shirt'),
    ('Развлечения', 'expense', 'expense_secondary', 'clapperboard'),
    ('Путешествия', 'expense', 'expense_secondary', 'plane'),
    ('Подарки', 'expense', 'expense_secondary', 'gift'),
    ('Красота и уход', 'expense', 'expense_secondary', 'sparkles'),
    ('Животные', 'expense', 'expense_secondary', 'paw-print'),
]

PALETTE = [
    '#2563eb', '#7c3aed', '#db2777', '#ea580c', '#16a34a', '#0891b2', '#ca8a04',
    '#dc2626', '#4f46e5', '#0f766e', '#9333ea', '#0284c7', '#65a30d', '#c2410c',
]


def _next_color(used_colors: list[str]) -> str:
    used = {item.lower() for item in used_colors if item}
    for color in PALETTE:
        if color.lower() not in used:
            return color
    return PALETTE[len(used_colors) % len(PALETTE)]


def upgrade() -> None:
    op.add_column(
        'categories',
        sa.Column('icon_name', sa.String(length=64), nullable=False, server_default='tag'),
    )

    connection = op.get_bind()

    for name, icon_name in ICON_BY_NAME.items():
        connection.execute(
            text("UPDATE categories SET icon_name = :icon_name WHERE name = :name"),
            {'icon_name': icon_name, 'name': name},
        )

    connection.execute(text("UPDATE categories SET color = '#2563eb' WHERE color IS NULL"))

    user_ids = [row[0] for row in connection.execute(text('SELECT id FROM users ORDER BY id')).fetchall()]
    for user_id in user_ids:
        used_colors = [row[0] for row in connection.execute(
            text('SELECT color FROM categories WHERE user_id = :user_id AND color IS NOT NULL ORDER BY id'),
            {'user_id': user_id},
        ).fetchall()]

        for name, kind, priority, icon_name in DEFAULT_CATEGORIES:
            exists = connection.execute(
                text(
                    '''
                    SELECT 1
                    FROM categories
                    WHERE user_id = :user_id AND name = :name AND kind = :kind AND priority = :priority
                    LIMIT 1
                    '''
                ),
                {'user_id': user_id, 'name': name, 'kind': kind, 'priority': priority},
            ).fetchone()
            if exists:
                continue

            color = _next_color(used_colors)
            used_colors.append(color)
            connection.execute(
                text(
                    '''
                    INSERT INTO categories (
                        user_id, name, kind, priority, color, icon_name, is_system, created_at, updated_at
                    ) VALUES (
                        :user_id, :name, :kind, :priority, :color, :icon_name, :is_system, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    '''
                ),
                {
                    'user_id': user_id,
                    'name': name,
                    'kind': kind,
                    'priority': priority,
                    'color': color,
                    'icon_name': icon_name,
                    'is_system': False,
                },
            )


def downgrade() -> None:
    op.drop_column('categories', 'icon_name')
