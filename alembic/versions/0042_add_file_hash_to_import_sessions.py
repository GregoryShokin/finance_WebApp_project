"""add file_hash to import_sessions

Revision ID: 0042_file_hash
Revises: 0041_ir_unique
Create Date: 2026-04-20

SHA-256 hash of the raw file bytes. Used to detect duplicate uploads:
if a user uploads the same file twice, the second upload returns the
existing active session instead of creating a new one.
"""

import sqlalchemy as sa
from alembic import op


revision = "0042_file_hash"
down_revision = "0041_ir_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "import_sessions",
        sa.Column("file_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_import_sessions_file_hash",
        "import_sessions",
        ["file_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_import_sessions_file_hash", table_name="import_sessions")
    op.drop_column("import_sessions", "file_hash")
