"""Add operation_type to transaction_category_rules + extend UNIQUE
(Этап 2 MVP launch — Обучаемый operation_type).

Revision ID: 0062
Revises: 0061
Create Date: 2026-05-03

Why: today only `category_id` is learned per (user, normalized_description).
`operation_type` (regular/debt/transfer/refund/...) is recomputed from
keyword heuristics + history-Counter on every import. Users with
"Перевод от Иван И." rows complain that they keep flipping the type to
debt — the system forgets. This migration prepares the storage; the
learning loop lands in app/repositories + app/services in Шаг 2.2+.

Decisions:
  - **Column on rules** (NOT a separate `transaction_op_type_rules` table).
    debt-rows already learn category through this rule. Adding op_type
    here closes the gap with one column. transfer/credit_disbursement/
    refund-rows are skipped at the committer level today and stay
    skipped — separate backlog.
  - **UNIQUE expanded to 4 columns** with `NULLS NOT DISTINCT`. Postgres
    16+ + SQLA 2.0.27+. The legacy 3-column UNIQUE allowed only one
    rule per (user, desc, cat); after the change the same shape stays —
    NULL is treated as a single value, so legacy rows (op_type=NULL)
    remain unique. With explicit op_types, the same (user, desc, cat)
    can host multiple rules differentiated by op_type — required for
    bulk-apply mixed clusters (Шаг 2.4).
  - **NO backfill** of op_type for existing rules. Guessing op_type from
    transaction history risks misclassifying active rules; legacy NULL
    rules keep working unchanged, new confirmations after Этап 2 fill
    the column over time.
  - **Defensive duplicate check** before dropping the old constraint —
    if any (user, desc, cat) triple has more than one row in prod (race
    leakage), the constraint drop would silently allow them to coexist.
    Migration aborts with a clear error so the maintainer can clean up.
  - **Partial index on operation_type** (NOT NULL) is for analytics
    queries; the UNIQUE itself is non-partial so `INSERT ... ON CONFLICT`
    in Шаг 2.2 can target it for both NULL and non-NULL op_types.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defensive sanity check — abort if duplicates somehow exist under the
    # legacy 3-column constraint. Should be impossible (UNIQUE enforces it),
    # but a leaked race or a manual SQL fix could violate. Better to fail
    # loudly than silently allow them to persist after the constraint widens.
    bind = op.get_bind()
    duplicates = bind.execute(sa.text(
        """
        SELECT user_id, normalized_description, category_id, COUNT(*)
        FROM transaction_category_rules
        GROUP BY user_id, normalized_description, category_id
        HAVING COUNT(*) > 1
        LIMIT 5
        """
    )).fetchall()
    if duplicates:
        raise RuntimeError(
            f"transaction_category_rules has duplicate (user, desc, cat) tuples "
            f"despite UNIQUE constraint: {duplicates!r}. Clean up before applying 0062."
        )

    op.add_column(
        "transaction_category_rules",
        sa.Column("operation_type", sa.String(32), nullable=True),
    )

    # Drop legacy 3-column UNIQUE; replace with 4-column NULLS NOT DISTINCT.
    op.drop_constraint(
        "uq_tx_cat_rule_user_desc_category",
        "transaction_category_rules",
        type_="unique",
    )
    op.create_index(
        "uq_tx_cat_rule_user_desc_cat_optype",
        "transaction_category_rules",
        ["user_id", "normalized_description", "category_id", "operation_type"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    # Read-performance index for analytics queries on op_type.
    op.create_index(
        "ix_rules_operation_type",
        "transaction_category_rules",
        ["operation_type"],
        postgresql_where=sa.text("operation_type IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_rules_operation_type", table_name="transaction_category_rules")
    op.drop_index(
        "uq_tx_cat_rule_user_desc_cat_optype",
        table_name="transaction_category_rules",
    )
    # Restore legacy 3-column UNIQUE. Will fail if there are now multiple
    # rules per (user, desc, cat) with different op_types — that is the
    # correct behaviour: the maintainer must reconcile the data before
    # downgrading the schema.
    op.create_unique_constraint(
        "uq_tx_cat_rule_user_desc_category",
        "transaction_category_rules",
        ["user_id", "normalized_description", "category_id"],
    )
    op.drop_column("transaction_category_rules", "operation_type")
