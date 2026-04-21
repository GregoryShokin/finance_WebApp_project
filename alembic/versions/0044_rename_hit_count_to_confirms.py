"""rename_hit_count_to_confirms

Revision ID: 0044_rename_confirms
Revises: 0043_rule_strength
Create Date: 2026-04-22

Переименовывает hit_count -> confirms в transaction_category_rules.
Исполняется после 0043: к этому моменту уже добавлены strength-поля,
и `hit_count` был только техническим именем счётчика подтверждений.
`confirms` — парное имя к `rejections` (добавлено в 0043).

Phase 2.2 of И-08. В коде ≤10 ссылок на hit_count (4 backend-файла +
2 frontend), переименование сделано в одном рефакторинге.
"""

from alembic import op


revision = "0044_rename_confirms"
down_revision = "0043_rule_strength"
branch_labels = None
depends_on = None


TABLE = "transaction_category_rules"


def upgrade() -> None:
    op.alter_column(TABLE, "hit_count", new_column_name="confirms")


def downgrade() -> None:
    op.alter_column(TABLE, "confirms", new_column_name="hit_count")
