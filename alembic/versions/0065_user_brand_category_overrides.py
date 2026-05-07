"""Per-user brand→category overrides (Brand registry Ph8).

Revision ID: 0065
Revises: 0064
Create Date: 2026-05-07

A user can override a brand's default `category_hint` for their own
accounting. Default behaviour: «Dodo Pizza» → «Кафе и рестораны» (from
seed). User says "for me it's «Доставка еды»" — that decision lives
here, persisted across imports. Resolver / confirm flow read this
table first, fall back to `Brand.category_hint` when no override.

UNIQUE(user_id, brand_id) enforces one override per user-brand pair —
re-applying replaces the previous override (no history of changes,
this is a configuration preference, not an audit log).

ON DELETE CASCADE all the way: deleting a user / brand / category
sweeps the override automatically; no orphan rows.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_brand_category_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "brand_id",
            sa.Integer(),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
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
        sa.UniqueConstraint(
            "user_id", "brand_id",
            name="uq_user_brand_category_overrides_user_brand",
        ),
    )


def downgrade() -> None:
    op.drop_table("user_brand_category_overrides")
