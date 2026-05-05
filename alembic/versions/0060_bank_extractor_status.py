"""Add extractor_status / extractor_last_tested_at / extractor_notes to banks
(MVP launch Этап 1, whitelist banks for import).

Revision ID: 0060
Revises: 0058
Create Date: 2026-05-03

Why: not every bank in the picker has a tested extractor. The import upload
flow blocks unsupported banks (Шаг 6); the picker visually flags them as
"скоро". Status lives on `banks` directly — a separate normalized table
costs a JOIN per /banks request and the data is a 30-row reference set.

Branching: 0060 branches off 0058 in parallel with 0059 (refresh_tokens,
Этап 0.1). When both land, a merge revision (0061_merge_heads) joins them.

Baseline data sync (which banks are 'supported' vs 'pending') lives in
`app.services.bank_service.BankService.ensure_extractor_status_baseline`,
called on FastAPI startup. The migration only sets the schema + default —
populating a list of supported codes here would force a new migration on
every whitelist change.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0060"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "banks",
        sa.Column(
            "extractor_status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.add_column(
        "banks",
        sa.Column(
            "extractor_last_tested_at",
            sa.Date(),
            nullable=True,
        ),
    )
    op.add_column(
        "banks",
        sa.Column(
            "extractor_notes",
            sa.Text(),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_banks_extractor_status",
        "banks",
        "extractor_status IN ('supported', 'in_review', 'pending', 'broken')",
    )
    op.create_index(
        "ix_banks_extractor_status",
        "banks",
        ["extractor_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_banks_extractor_status", table_name="banks")
    op.drop_constraint("ck_banks_extractor_status", "banks", type_="check")
    op.drop_column("banks", "extractor_notes")
    op.drop_column("banks", "extractor_last_tested_at")
    op.drop_column("banks", "extractor_status")
