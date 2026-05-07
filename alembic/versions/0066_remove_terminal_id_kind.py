"""Drop 'terminal_id' from brand_patterns.kind CHECK constraint (Brand registry, post-Ph8).

Revision ID: 0066
Revises: 0065
Create Date: 2026-05-07

The 'terminal_id' kind was added in 0064 on the assumption that the
4-digit suffix in T-Bank SBP descriptions ("26033 MOR SBP 0387") was a
per-store terminal identifier. It is in fact the last 4 of the *payer's*
card — a property of the user, not the merchant — and never should have
participated in brand resolution. Live DB has zero patterns of this kind
(verified before this migration), so the drop is non-destructive.

Field-level rename (`ExtractedTokens.terminal_id` → `card_last4`) is
done in code; this migration only removes the dead enum value from the
CHECK constraint so future inserts can't reintroduce it.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_brand_patterns_kind", "brand_patterns", type_="check",
    )
    op.create_check_constraint(
        "ck_brand_patterns_kind",
        "brand_patterns",
        "kind IN ('text', 'sbp_merchant_id', 'org_full', 'alias_exact')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_brand_patterns_kind", "brand_patterns", type_="check",
    )
    op.create_check_constraint(
        "ck_brand_patterns_kind",
        "brand_patterns",
        "kind IN ('text', 'sbp_merchant_id', 'terminal_id', 'org_full', 'alias_exact')",
    )
