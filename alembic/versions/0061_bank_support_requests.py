"""Add bank_support_requests table (Этап 1.4 MVP launch).

Revision ID: 0061
Revises: 0060
Create Date: 2026-05-03

Why: when a user lands on the import flow with a bank that's not in the
extractor whitelist (Шаг 6 guards the upload), they should be able to
record interest in having that bank supported. The list is the maintainer's
queue: pending → in_review → added/rejected.

Decision (2026-05-03): JSON-only payload. No sample-file uploads in MVP —
PII risks (third-party statements with full names, contract numbers, card
last-4 digits) require encryption-at-rest, scheduled cleanup, and a Docker
volume that survives `compose down`. All three are deferred. Maintainer
collects sample fixtures out of band and drops them into
`tests/fixtures/statements/raw/` (gitignored).

`bank_id` is nullable: a user may type a bank name that's not in the
`banks` table at all (a niche regional bank we never seeded), in which
case `bank_name` carries the raw input string.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0061"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bank_support_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "bank_id",
            sa.Integer(),
            sa.ForeignKey("banks.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("bank_name", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'pending'"),
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
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_bank_support_requests_status",
        "bank_support_requests",
        "status IN ('pending', 'in_review', 'added', 'rejected')",
    )
    op.create_index(
        "ix_bank_support_requests_status",
        "bank_support_requests",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_bank_support_requests_status", table_name="bank_support_requests")
    op.drop_constraint(
        "ck_bank_support_requests_status",
        "bank_support_requests",
        type_="check",
    )
    op.drop_table("bank_support_requests")
