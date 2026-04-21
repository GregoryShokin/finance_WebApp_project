"""rule_strength_fields

Revision ID: 0043_rule_strength
Revises: 0042_file_hash
Create Date: 2026-04-22

Добавляет strength-поля (rejections, scope, is_active, bank_code,
account_id_scope, identifier_key, identifier_value) в
transaction_category_rules. Миграция данных: существующие правила
с hit_count >= 5 -> is_active=True, scope=legacy_pattern.

Phase 2.1 of И-08. `scope` is a plain VARCHAR, not a PG enum: Postgres
enums are painful to evolve (ALTER TYPE ... ADD VALUE, locks), and
scope will keep evolving. Allowed values are validated in Python.
"""

import sqlalchemy as sa
from alembic import op


revision = "0043_rule_strength"
down_revision = "0042_file_hash"
branch_labels = None
depends_on = None


TABLE = "transaction_category_rules"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "rejections",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "scope",
            sa.String(length=32),
            nullable=False,
            server_default="legacy_pattern",
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("bank_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("account_id_scope", sa.Integer(), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("identifier_key", sa.String(length=32), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("identifier_value", sa.String(length=128), nullable=True),
    )

    op.create_foreign_key(
        "fk_tx_cat_rule_account_scope",
        TABLE,
        "accounts",
        ["account_id_scope"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_tx_cat_rule_user_scope_active",
        TABLE,
        ["user_id", "scope", "is_active"],
    )
    op.create_index(
        "ix_tx_cat_rule_user_identifier",
        TABLE,
        ["user_id", "identifier_key", "identifier_value"],
    )
    op.create_index(
        "ix_tx_cat_rule_bank_code",
        TABLE,
        ["bank_code"],
    )

    # Data migration: activate rules that have already proven themselves.
    # Guard against double-apply by only touching rows still in the default
    # legacy state (scope='legacy_pattern', is_active=False).
    op.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
            SET is_active = (hit_count >= 5)
            WHERE scope = 'legacy_pattern' AND is_active = FALSE
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_tx_cat_rule_bank_code", table_name=TABLE)
    op.drop_index("ix_tx_cat_rule_user_identifier", table_name=TABLE)
    op.drop_index("ix_tx_cat_rule_user_scope_active", table_name=TABLE)

    op.drop_constraint("fk_tx_cat_rule_account_scope", TABLE, type_="foreignkey")

    op.drop_column(TABLE, "identifier_value")
    op.drop_column(TABLE, "identifier_key")
    op.drop_column(TABLE, "account_id_scope")
    op.drop_column(TABLE, "bank_code")
    op.drop_column(TABLE, "is_active")
    op.drop_column(TABLE, "scope")
    op.drop_column(TABLE, "rejections")
