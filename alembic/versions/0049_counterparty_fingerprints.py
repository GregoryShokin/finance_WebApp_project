"""add counterparty_fingerprints — fingerprint→counterparty binding (Phase 3)

Revision ID: 0049
Revises: 0048
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "counterparty_fingerprints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(32), nullable=False),
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
        sa.UniqueConstraint("user_id", "fingerprint", name="uq_cp_fingerprint_user_fp"),
    )
    op.create_index("ix_counterparty_fingerprints_id", "counterparty_fingerprints", ["id"])
    op.create_index("ix_counterparty_fingerprints_user_id", "counterparty_fingerprints", ["user_id"])
    op.create_index(
        "ix_counterparty_fingerprints_fingerprint",
        "counterparty_fingerprints",
        ["fingerprint"],
    )
    op.create_index(
        "ix_counterparty_fingerprints_counterparty_id",
        "counterparty_fingerprints",
        ["counterparty_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_counterparty_fingerprints_counterparty_id", table_name="counterparty_fingerprints")
    op.drop_index("ix_counterparty_fingerprints_fingerprint", table_name="counterparty_fingerprints")
    op.drop_index("ix_counterparty_fingerprints_user_id", table_name="counterparty_fingerprints")
    op.drop_index("ix_counterparty_fingerprints_id", table_name="counterparty_fingerprints")
    op.drop_table("counterparty_fingerprints")
