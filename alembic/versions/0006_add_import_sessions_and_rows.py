"""add import sessions and rows

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="csv"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="uploaded"),
        sa.Column("file_content", sa.Text(), nullable=False),
        sa.Column("detected_columns", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("parse_settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("mapping_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("summary_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_import_sessions_id", "import_sessions", ["id"], unique=False)
    op.create_index("ix_import_sessions_user_id", "import_sessions", ["user_id"], unique=False)
    op.create_index("ix_import_sessions_status", "import_sessions", ["status"], unique=False)
    op.create_index("ix_import_sessions_account_id", "import_sessions", ["account_id"], unique=False)

    op.create_table(
        "import_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("import_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("raw_data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("normalized_data_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_transaction_id", sa.Integer(), sa.ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_import_rows_id", "import_rows", ["id"], unique=False)
    op.create_index("ix_import_rows_session_id", "import_rows", ["session_id"], unique=False)
    op.create_index("ix_import_rows_status", "import_rows", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_import_rows_status", table_name="import_rows")
    op.drop_index("ix_import_rows_session_id", table_name="import_rows")
    op.drop_index("ix_import_rows_id", table_name="import_rows")
    op.drop_table("import_rows")

    op.drop_index("ix_import_sessions_account_id", table_name="import_sessions")
    op.drop_index("ix_import_sessions_status", table_name="import_sessions")
    op.drop_index("ix_import_sessions_user_id", table_name="import_sessions")
    op.drop_index("ix_import_sessions_id", table_name="import_sessions")
    op.drop_table("import_sessions")
