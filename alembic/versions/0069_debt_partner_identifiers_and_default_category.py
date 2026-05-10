"""debt_partner_identifiers + DebtPartner.default_category_id

Revision ID: 0069
Revises: 0068
Create Date: 2026-05-10

Backs the unified «+ Имя / Бренд» moderator entry point: when the user
names a personal contact on an import row, we persist the identifier
tokens of that row (phone / contract / person_hash) so future imports
auto-resolve the same person — mirror of how `brand_identifiers` works
for merchant brands.

Two changes:

  1. `debt_partners.default_category_id` (nullable FK → categories.id
     ON DELETE SET NULL). Optional category hint pinned by the user the
     first time they name a contact in the import moderator. Treated as
     a hint at confirm time, never auto-applied to debt-operation rows
     (debt direction drives the category for those).
  2. `debt_partner_identifiers` table. Same shape as `brand_identifiers`
     with the FK re-pointed at `debt_partners`. UNIQUE (user_id,
     identifier_kind, identifier_value) so re-bind is upsert-safe.

`identifier_kind` is constrained at the application layer (only
{phone, contract, person_hash} are accepted). We don't add a CHECK
constraint here so future kinds can be onboarded without a migration —
spec convention matches `brand_identifiers`.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0069"
down_revision: Union[str, None] = "0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. debt_partners.default_category_id — optional hint set when the
    #    user first names a contact in the moderator. Nullable; existing
    #    rows stay NULL.
    op.add_column(
        "debt_partners",
        sa.Column(
            "default_category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_debt_partners_default_category_id",
        "debt_partners",
        ["default_category_id"],
    )

    # 2. debt_partner_identifiers — mirror of brand_identifiers (0067).
    op.create_table(
        "debt_partner_identifiers",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("identifier_kind", sa.String(16), nullable=False),
        sa.Column("identifier_value", sa.String(128), nullable=False),
        sa.Column(
            "debt_partner_id",
            sa.Integer(),
            sa.ForeignKey("debt_partners.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "confirms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "identifier_kind", "identifier_value",
            name="uq_debt_partner_identifier_user_kind_value",
        ),
    )


def downgrade() -> None:
    op.drop_table("debt_partner_identifiers")
    op.drop_index(
        "ix_debt_partners_default_category_id",
        table_name="debt_partners",
    )
    op.drop_column("debt_partners", "default_category_id")
