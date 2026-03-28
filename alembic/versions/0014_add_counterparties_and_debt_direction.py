"""add counterparties and debt direction

Revision ID: 0014
Revises: 0013
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _has_fk(table_name: str, fk_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return fk_name in {fk.get("name") for fk in inspector.get_foreign_keys(table_name)}


def upgrade() -> None:
    if not _has_table("counterparties"):
        op.create_table(
            "counterparties",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "opening_receivable_amount",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "opening_payable_amount",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )

    if not _has_index("counterparties", "ix_counterparties_user_id"):
        op.create_index("ix_counterparties_user_id", "counterparties", ["user_id"], unique=False)

    if not _has_column("transactions", "counterparty_id"):
        op.add_column("transactions", sa.Column("counterparty_id", sa.Integer(), nullable=True))

    if not _has_column("transactions", "debt_direction"):
        op.add_column("transactions", sa.Column("debt_direction", sa.String(length=32), nullable=True))

    if _has_column("transactions", "counterparty_id") and not _has_fk(
        "transactions", "fk_transactions_counterparty_id_counterparties"
    ):
        op.create_foreign_key(
            "fk_transactions_counterparty_id_counterparties",
            "transactions",
            "counterparties",
            ["counterparty_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if _has_column("transactions", "counterparty_id") and not _has_index(
        "transactions", "ix_transactions_counterparty_id"
    ):
        op.create_index("ix_transactions_counterparty_id", "transactions", ["counterparty_id"], unique=False)

    if _has_column("transactions", "debt_direction") and not _has_index(
        "transactions", "ix_transactions_debt_direction"
    ):
        op.create_index("ix_transactions_debt_direction", "transactions", ["debt_direction"], unique=False)


def downgrade() -> None:
    if _has_index("transactions", "ix_transactions_debt_direction"):
        op.drop_index("ix_transactions_debt_direction", table_name="transactions")

    if _has_index("transactions", "ix_transactions_counterparty_id"):
        op.drop_index("ix_transactions_counterparty_id", table_name="transactions")

    if _has_fk("transactions", "fk_transactions_counterparty_id_counterparties"):
        op.drop_constraint(
            "fk_transactions_counterparty_id_counterparties",
            "transactions",
            type_="foreignkey",
        )

    if _has_column("transactions", "debt_direction"):
        op.drop_column("transactions", "debt_direction")

    if _has_column("transactions", "counterparty_id"):
        op.drop_column("transactions", "counterparty_id")

    if _has_index("counterparties", "ix_counterparties_user_id"):
        op.drop_index("ix_counterparties_user_id", table_name="counterparties")

    if _has_table("counterparties"):
        op.drop_table("counterparties")
