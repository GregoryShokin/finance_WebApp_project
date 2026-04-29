"""add debt_partners + transactions.debt_partner_id (split debt role off Counterparty)

Revision ID: 0051
Revises: 0050
Create Date: 2026-04-24

Why: Counterparty is currently used for two semantically different things —
merchants/services in cluster moderation ("Пятёрочка", "Яндекс Такси") and
debtors/creditors on debt transactions ("Паша", "Отец"). Mixing them pollutes
both UIs (the debt selector offers every merchant; the cluster moderator's
list is cluttered with people you owe money to). This migration introduces a
dedicated DebtPartner entity; data migration happens in a separate script
(scripts/split_counterparties_into_debt_partners.py) so the DDL stays
reversible independently of data moves.
"""
from alembic import op
import sqlalchemy as sa


revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "debt_partners",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
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
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_debt_partner_user_name"),
    )
    op.create_index("ix_debt_partners_id", "debt_partners", ["id"])
    op.create_index("ix_debt_partners_user_id", "debt_partners", ["user_id"])
    op.create_index("ix_debt_partners_name", "debt_partners", ["name"])

    op.add_column(
        "transactions",
        sa.Column(
            "debt_partner_id",
            sa.Integer(),
            sa.ForeignKey("debt_partners.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_transactions_debt_partner_id",
        "transactions",
        ["debt_partner_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_debt_partner_id", table_name="transactions")
    op.drop_column("transactions", "debt_partner_id")
    op.drop_index("ix_debt_partners_name", table_name="debt_partners")
    op.drop_index("ix_debt_partners_user_id", table_name="debt_partners")
    op.drop_index("ix_debt_partners_id", table_name="debt_partners")
    op.drop_table("debt_partners")
