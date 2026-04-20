"""add unique constraint on import_rows(session_id, row_index)

Revision ID: 0041_ir_unique
Revises: 0040_snap_align_dash
Create Date: 2026-04-20

Prevents race conditions where build_preview fires twice and ends up
with two ImportRow entries per (session_id, row_index), which then
both get committed — creating duplicate transactions.
"""

from alembic import op


revision = "0041_ir_unique"
down_revision = "0040_snap_align_dash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_import_rows_session_row_index",
        "import_rows",
        ["session_id", "row_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_import_rows_session_row_index",
        "import_rows",
        type_="unique",
    )
