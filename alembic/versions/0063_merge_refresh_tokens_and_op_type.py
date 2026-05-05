"""Merge refresh_tokens (Этап 0.1) and op_type learning (Этап 2) chains.

Revision ID: 0063
Revises: 0059, 0062
Create Date: 2026-05-04

Why: parallel feature work landed two independent migration chains off 0058 —
  - 0058 → 0059 (refresh_tokens, Этап 0.1)
  - 0058 → 0060 → 0061 → 0062 (bank whitelist + bank support requests + op_type
    learning, Этапы 1+2)

Both reference 0058 as their down_revision, producing two heads. Without a
merge revision `alembic upgrade head` fails with "Multiple head revisions".
This migration is the join point — it has no schema changes, just declares
that the two chains converge here. After this, all new migrations chain off
0063 (single head) and the branching is closed.

Downgrade behaviour — `alembic downgrade -1` from a merge revision raises
"Ambiguous walk" because Alembic cannot pick between the two parent chains
without an explicit target. **Use a concrete revision** instead:
  - `alembic downgrade 0059` — keeps refresh_tokens, drops Этапы 1+2 schema
  - `alembic downgrade 0062` — keeps Этапы 1+2 schema, drops refresh_tokens
  - `alembic downgrade 0058` — drops everything from both chains
This is expected Alembic behaviour for merge revisions, not a bug in this
migration.

References:
- §22 of "Спецификация — Пайплайн импорта" (op_type learning)
- §21 of the same spec (bank whitelist)
- "Фича — Refresh Token" backlog card (Этап 0.1)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0063"
down_revision: Union[str, Sequence[str], None] = ("0059", "0062")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No schema changes — pure join of the two parallel chains."""
    pass


def downgrade() -> None:
    """Returns to the pre-merge multi-head state. Each parent chain
    (0059, 0062) remains independently down-gradable from there."""
    pass
