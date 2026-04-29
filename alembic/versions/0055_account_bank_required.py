"""Make accounts.bank_id NOT NULL and seed an "Unknown bank" placeholder.

Revision ID: 0055
Revises: 0054
Create Date: 2026-04-29

Why: spec invariant — every account MUST be tied to a concrete bank so that
statement extractors and counterparty-binding logic resolve correctly.

Pre-migration: orphan accounts (bank_id IS NULL) are TEST-only data on this
deployment; they will be deleted as part of this migration. Real users will
recreate them through the UI which now forces a bank selection.

The "Unknown bank" placeholder is seeded so that users with statements from
small/unsupported banks have a fallback option. Skeleton/fingerprint logic
still works under unknown bank_code, only the bank-specific mechanics
(Yandex Сплит/Дебет, Sberbank PDF quirks) won't trigger.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Seed the "Unknown bank" placeholder if it doesn't exist yet.
    #    code='unknown' is the canonical sentinel used elsewhere in the code.
    bind.execute(
        sa.text(
            """
            INSERT INTO banks (name, code, is_popular)
            VALUES ('Неопределённый банк', 'unknown', false)
            ON CONFLICT (code) DO NOTHING
            """
        )
    )

    # 2. Drop accounts that are still orphaned (bank_id IS NULL). On this
    #    deployment they are confirmed test-only by the user; in any other
    #    deployment a backfill step must run before this migration.
    #
    #    Cascade deletes will remove related transactions; this is intentional
    #    given the test-only nature of the affected rows. If you re-run this
    #    migration on a non-test database, BACK UP FIRST and substitute the
    #    DELETE with an UPDATE that points at the placeholder bank.
    bind.execute(sa.text("DELETE FROM accounts WHERE bank_id IS NULL"))

    # 3. Tighten the column. ondelete='RESTRICT' so banks can't be removed
    #    while any account still references them — banks are reference data,
    #    not user-owned, so SET NULL was always semantically wrong here.
    op.alter_column(
        "accounts",
        "bank_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_constraint("accounts_bank_id_fkey", "accounts", type_="foreignkey")
    op.create_foreign_key(
        "accounts_bank_id_fkey",
        "accounts",
        "banks",
        ["bank_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("accounts_bank_id_fkey", "accounts", type_="foreignkey")
    op.create_foreign_key(
        "accounts_bank_id_fkey",
        "accounts",
        "banks",
        ["bank_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column(
        "accounts",
        "bank_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    # Note: we do NOT remove the "Неопределённый банк" record on downgrade —
    # it may now be referenced by accounts created after the upgrade.
