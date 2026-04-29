"""add counterparty_identifiers — identifier→counterparty binding (cross-account)

Revision ID: 0050
Revises: 0049
Create Date: 2026-04-24

Why: CounterpartyFingerprint bakes account_id + bank into the fingerprint, so a
binding created on one statement (e.g. Tinkoff credit card) doesn't resolve the
same phone / contract / IBAN on another statement (e.g. Tinkoff debit). This
table stores a narrower, identifier-keyed binding that is cross-account and
cross-bank — "phone +79281935935 → Арендодатель" is a fact about the person,
not about which of your accounts you paid them from.
"""
from alembic import op
import sqlalchemy as sa


revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparty_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("identifier_kind", sa.String(16), nullable=False),
        sa.Column("identifier_value", sa.String(128), nullable=False),
        sa.Column(
            "counterparty_id",
            sa.Integer(),
            sa.ForeignKey("counterparties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("confirms", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "identifier_kind", "identifier_value",
            name="uq_cp_identifier_user_kind_value",
        ),
    )
    op.create_index("ix_counterparty_identifiers_id", "counterparty_identifiers", ["id"])
    op.create_index("ix_counterparty_identifiers_user_id", "counterparty_identifiers", ["user_id"])
    op.create_index(
        "ix_counterparty_identifiers_counterparty_id",
        "counterparty_identifiers",
        ["counterparty_id"],
    )
    op.create_index(
        "ix_counterparty_identifiers_lookup",
        "counterparty_identifiers",
        ["user_id", "identifier_kind", "identifier_value"],
    )


def downgrade() -> None:
    op.drop_index("ix_counterparty_identifiers_lookup", table_name="counterparty_identifiers")
    op.drop_index("ix_counterparty_identifiers_counterparty_id", table_name="counterparty_identifiers")
    op.drop_index("ix_counterparty_identifiers_user_id", table_name="counterparty_identifiers")
    op.drop_index("ix_counterparty_identifiers_id", table_name="counterparty_identifiers")
    op.drop_table("counterparty_identifiers")
