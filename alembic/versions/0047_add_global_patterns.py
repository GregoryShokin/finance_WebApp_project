"""add global_patterns and global_pattern_votes tables (Layer 3)

Revision ID: 0047
Revises: 0046
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_patterns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bank_code", sa.String(64), nullable=False),
        sa.Column("skeleton", sa.String(500), nullable=False),
        sa.Column("category_kind", sa.String(16), nullable=False),
        sa.Column("suggested_category_name", sa.String(255), nullable=False),
        sa.Column("user_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_confirms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bank_code", "skeleton", "suggested_category_name",
                            name="uq_global_pattern_bank_skeleton_cat"),
    )
    op.create_index("ix_global_patterns_id", "global_patterns", ["id"])
    op.create_index("ix_global_patterns_bank_code", "global_patterns", ["bank_code"])
    op.create_index("ix_global_patterns_skeleton", "global_patterns", ["skeleton"])

    op.create_table(
        "global_pattern_votes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("pattern_id", sa.Integer(), sa.ForeignKey("global_patterns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vote_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pattern_id", "user_id", name="uq_global_vote_pattern_user"),
    )
    op.create_index("ix_global_pattern_votes_id", "global_pattern_votes", ["id"])
    op.create_index("ix_global_pattern_votes_pattern_id", "global_pattern_votes", ["pattern_id"])
    op.create_index("ix_global_pattern_votes_user_id", "global_pattern_votes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_global_pattern_votes_user_id", "global_pattern_votes")
    op.drop_index("ix_global_pattern_votes_pattern_id", "global_pattern_votes")
    op.drop_index("ix_global_pattern_votes_id", "global_pattern_votes")
    op.drop_table("global_pattern_votes")

    op.drop_index("ix_global_patterns_skeleton", "global_patterns")
    op.drop_index("ix_global_patterns_bank_code", "global_patterns")
    op.drop_index("ix_global_patterns_id", "global_patterns")
    op.drop_table("global_patterns")
