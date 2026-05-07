"""Brands + brand_patterns tables (Brand registry §2 — Ph1).

Revision ID: 0064
Revises: 0063
Create Date: 2026-05-07

Brand-recognition layer that sits ABOVE the existing fingerprint/skeleton
counterparty bindings. A `Brand` is the canonical identity of a merchant
chain ("Пятёрочка", "Вкусно и точка"); a `BrandPattern` is one concrete
way that brand appears in raw bank-statement data (text substring, SBP
merchant_id, terminal_id, exact org-form, exact alias).

Scope is dual:
  * `is_global=True` patterns are seeded by the maintainer and visible to
    every user. `created_by_user_id` is NULL.
  * `is_global=False` patterns are private to one user (`scope_user_id`),
    typically created when the user manually attaches a row to a brand
    during inline-prompt confirmation (Brand registry §6 scenario C).

The resolver tries user-scope first, then global, so a private pattern can
override a global one ("vkusno" → "Кафе у Иваныча" wins over global
"vkusno" → "Вкусно и точка" if the user has set it that way).

Strength counters (`confirms`/`rejections`) follow the
`TransactionCategoryRule` pattern from §10.2 — tracked per-pattern, not
per-brand, because a brand may have many patterns of varying reliability
(e.g. SBP merchant_id is rock-solid; a 4-letter text alias may collide).
Auto-deactivation is a Ph6 concern — for now `is_active` is just a flag.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("canonical_name", sa.String(128), nullable=False),
        sa.Column("category_hint", sa.String(64), nullable=True),
        sa.Column(
            "is_global",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.UniqueConstraint("slug", name="uq_brands_slug"),
    )
    op.create_index("ix_brands_is_global", "brands", ["is_global"])
    op.create_index(
        "ix_brands_created_by_user_id",
        "brands",
        ["created_by_user_id"],
    )

    op.create_table(
        "brand_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "brand_id",
            sa.Integer(),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("pattern", sa.String(256), nullable=False),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "is_regex",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "confirms",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "rejections",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_global",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "scope_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
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
    )
    op.create_check_constraint(
        "ck_brand_patterns_kind",
        "brand_patterns",
        "kind IN ('text', 'sbp_merchant_id', 'terminal_id', 'org_full', 'alias_exact')",
    )
    op.create_check_constraint(
        "ck_brand_patterns_scope_consistency",
        "brand_patterns",
        "(is_global = true AND scope_user_id IS NULL)"
        " OR (is_global = false AND scope_user_id IS NOT NULL)",
    )
    op.create_index(
        "ix_brand_patterns_resolver",
        "brand_patterns",
        ["kind", "is_active", "is_global", "scope_user_id"],
    )
    op.create_index(
        "uq_brand_patterns_brand_kind_pattern_scope",
        "brand_patterns",
        ["brand_id", "kind", "pattern", "scope_user_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_brand_patterns_brand_kind_pattern_scope",
        table_name="brand_patterns",
    )
    op.drop_index("ix_brand_patterns_resolver", table_name="brand_patterns")
    op.drop_constraint(
        "ck_brand_patterns_scope_consistency",
        "brand_patterns",
        type_="check",
    )
    op.drop_constraint("ck_brand_patterns_kind", "brand_patterns", type_="check")
    op.drop_table("brand_patterns")

    op.drop_index("ix_brands_created_by_user_id", table_name="brands")
    op.drop_index("ix_brands_is_global", table_name="brands")
    op.drop_table("brands")
