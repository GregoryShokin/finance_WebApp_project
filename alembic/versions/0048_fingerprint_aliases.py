"""add fingerprint_aliases table — user-driven cluster merges

Revision ID: 0048
Revises: 0047
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa


revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fingerprint_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_fingerprint", sa.String(32), nullable=False),
        sa.Column("target_fingerprint", sa.String(32), nullable=False),
        sa.Column("confirms", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_fingerprint", name="uq_fp_alias_user_source"),
    )
    op.create_index("ix_fingerprint_aliases_id", "fingerprint_aliases", ["id"])
    op.create_index("ix_fingerprint_aliases_user_id", "fingerprint_aliases", ["user_id"])
    op.create_index(
        "ix_fingerprint_aliases_source_fingerprint",
        "fingerprint_aliases",
        ["source_fingerprint"],
    )
    op.create_index(
        "ix_fingerprint_aliases_target_fingerprint",
        "fingerprint_aliases",
        ["target_fingerprint"],
    )


def downgrade() -> None:
    op.drop_index("ix_fingerprint_aliases_target_fingerprint", table_name="fingerprint_aliases")
    op.drop_index("ix_fingerprint_aliases_source_fingerprint", table_name="fingerprint_aliases")
    op.drop_index("ix_fingerprint_aliases_user_id", table_name="fingerprint_aliases")
    op.drop_index("ix_fingerprint_aliases_id", table_name="fingerprint_aliases")
    op.drop_table("fingerprint_aliases")
