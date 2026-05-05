from __future__ import annotations

from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.transaction_category_rule import (
    ACTIVE_PREVIEW_SCOPES,
    TransactionCategoryRule,
)


# Index name used by both PG and SQLite ON CONFLICT clauses. Defined on the
# 4-column UNIQUE in migration 0062 (with NULLS NOT DISTINCT on PG so that
# legacy rows with operation_type=NULL still participate in conflict
# detection). On SQLite the same index name is created from the model
# metadata (without NULLS NOT DISTINCT — SQLite's behaviour is the same as
# Postgres NULLS NOT DISTINCT for our purposes here, since SQLite treats
# NULLs as equal in UNIQUE).
_RULE_UPSERT_INDEX = "uq_tx_cat_rule_user_desc_cat_optype"


class TransactionCategoryRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_best_rule(
        self,
        *,
        user_id: int,
        normalized_description: str,
        want_op_type: bool = False,
    ) -> TransactionCategoryRule | None:
        """Return the highest-confidence matching rule for skeleton-based
        preview lookup. §6.5 + PR1 cleanup: only `is_active=True` rules
        with one of the post-migration scopes (`specific`, `general`) are
        eligible. Legacy `bank` / `legacy_pattern` rules stay in the table
        per §11.3 (history, possible review) but never silently apply.
        Inactive rules also never match — even if they share a skeleton.

        ``want_op_type``: Этап 2. When True, run a two-pass lookup:
          1. Prefer rules with ``operation_type IS NOT NULL`` (post-Этап-2
             learned rules carry an explicit op_type).
          2. Fall back to legacy rules (``operation_type IS NULL``) if no
             learned rule exists. Legacy rules drive category-suggestion
             only; the op_type path uses keyword/history flow.
        Default ``False`` keeps the old single-pass behaviour for callers
        that don't care about op_type.
        """
        base_filters = (
            TransactionCategoryRule.user_id == user_id,
            TransactionCategoryRule.normalized_description == normalized_description,
            TransactionCategoryRule.is_active.is_(True),
            TransactionCategoryRule.scope.in_(tuple(ACTIVE_PREVIEW_SCOPES)),
        )
        order_by = (
            TransactionCategoryRule.confirms.desc(),
            TransactionCategoryRule.updated_at.desc(),
            TransactionCategoryRule.id.desc(),
        )

        if want_op_type:
            with_op_type = (
                self.db.query(TransactionCategoryRule)
                .filter(*base_filters, TransactionCategoryRule.operation_type.isnot(None))
                .order_by(*order_by)
                .first()
            )
            if with_op_type is not None:
                return with_op_type

        return (
            self.db.query(TransactionCategoryRule)
            .filter(*base_filters)
            .order_by(*order_by)
            .first()
        )

    def bulk_upsert(
        self,
        *,
        user_id: int,
        normalized_description: str,
        category_id: int,
        confirms_delta: int,
        original_description: str | None = None,
        operation_type: str | None = None,
    ) -> tuple[TransactionCategoryRule, bool]:
        """Find-or-create a rule and set its confirms count in one shot.

        Used by the bulk-cluster moderator action — one UI click validates N
        rows, so the rule should jump straight to `confirms = N` on creation
        (or `+= N` on an existing rule). Returns `(rule, is_new)`.

        Strength-level side effects (activation / generalization) stay in
        `RuleStrengthService.on_confirmed(confirms_delta=N-1)`, which the
        caller invokes after this. We flush but don't commit — the caller
        owns the transaction.

        Этап 2: Race-safe via INSERT ... ON CONFLICT DO NOTHING + SELECT.
        Two parallel callers for the same (user, desc, cat, op_type) tuple
        no longer deadlock or duplicate — Postgres index UNIQUE rejects
        the second insert atomically. is_new is detected via id-membership
        before/after the insert.

        Этап 2: ``operation_type`` is the new key column. NULL preserved
        for legacy rows; on Postgres the UNIQUE has NULLS NOT DISTINCT so
        a single legacy NULL row exists per (user, desc, cat).
        """
        if confirms_delta < 1:
            raise ValueError(f"confirms_delta must be >= 1, got {confirms_delta}")

        existing_id = self._find_id(
            user_id=user_id,
            normalized_description=normalized_description,
            category_id=category_id,
            operation_type=operation_type,
        )
        if existing_id is not None:
            rule = self.db.get(TransactionCategoryRule, existing_id)
            if original_description and not rule.original_description:
                rule.original_description = original_description
                self.db.add(rule)
                self.db.flush()
            return rule, False

        # Race: another caller may have created it between our SELECT and
        # INSERT. ON CONFLICT DO NOTHING returns 0 rows in that case; we
        # then re-SELECT and treat as existing.
        values: dict[str, Any] = {
            "user_id": user_id,
            "normalized_description": normalized_description,
            "original_description": original_description,
            "category_id": category_id,
            "operation_type": operation_type,
            "confirms": Decimal("0"),  # on_confirmed applies the delta
        }
        inserted_id = self._insert_or_nothing(values)
        if inserted_id is not None:
            self.db.flush()
            return self.db.get(TransactionCategoryRule, inserted_id), True

        existing_id = self._find_id(
            user_id=user_id,
            normalized_description=normalized_description,
            category_id=category_id,
            operation_type=operation_type,
        )
        rule = self.db.get(TransactionCategoryRule, existing_id)
        if rule is not None and original_description and not rule.original_description:
            rule.original_description = original_description
            self.db.add(rule)
            self.db.flush()
        return rule, False

    def upsert(
        self,
        *,
        user_id: int,
        normalized_description: str,
        category_id: int,
        original_description: str | None = None,
        user_label: str | None = None,
        operation_type: str | None = None,
    ) -> TransactionCategoryRule:
        """Race-safe upsert via ON CONFLICT (user, desc, cat, op_type) DO
        UPDATE SET confirms = confirms + 1.

        Этап 2: ``operation_type`` is part of the conflict key. Two
        confirmations for the same (user, desc, cat) but different op_type
        produce two distinct rules — required for "Иван-зарплата vs Иван-долг".
        """
        existing_id = self._find_id(
            user_id=user_id,
            normalized_description=normalized_description,
            category_id=category_id,
            operation_type=operation_type,
        )
        if existing_id is not None:
            rule = self.db.get(TransactionCategoryRule, existing_id)
            rule.confirms = (rule.confirms or Decimal("0")) + Decimal("1")
            if original_description and not rule.original_description:
                rule.original_description = original_description
            if user_label is not None:
                rule.user_label = user_label
            self.db.add(rule)
            self.db.flush()
            return rule

        values: dict[str, Any] = {
            "user_id": user_id,
            "normalized_description": normalized_description,
            "original_description": original_description,
            "user_label": user_label,
            "category_id": category_id,
            "operation_type": operation_type,
            "confirms": Decimal("1"),
        }
        inserted_id = self._insert_or_nothing(values)
        if inserted_id is not None:
            self.db.flush()
            return self.db.get(TransactionCategoryRule, inserted_id)

        # Lost the race — re-fetch and increment.
        existing_id = self._find_id(
            user_id=user_id,
            normalized_description=normalized_description,
            category_id=category_id,
            operation_type=operation_type,
        )
        rule = self.db.get(TransactionCategoryRule, existing_id)
        if rule is not None:
            rule.confirms = (rule.confirms or Decimal("0")) + Decimal("1")
            if original_description and not rule.original_description:
                rule.original_description = original_description
            if user_label is not None:
                rule.user_label = user_label
            self.db.add(rule)
            self.db.flush()
        return rule

    def _find_id(
        self,
        *,
        user_id: int,
        normalized_description: str,
        category_id: int,
        operation_type: str | None,
    ) -> int | None:
        """SELECT id by 4-tuple key. NULL operation_type matches via IS NULL
        (SQLAlchemy's `==` translates None to IS NULL when the column is
        nullable, but only via .is_() to be explicit)."""
        q = self.db.query(TransactionCategoryRule.id).filter(
            TransactionCategoryRule.user_id == user_id,
            TransactionCategoryRule.normalized_description == normalized_description,
            TransactionCategoryRule.category_id == category_id,
        )
        if operation_type is None:
            q = q.filter(TransactionCategoryRule.operation_type.is_(None))
        else:
            q = q.filter(TransactionCategoryRule.operation_type == operation_type)
        return q.scalar()

    def _insert_or_nothing(self, values: dict[str, Any]) -> int | None:
        """Atomic INSERT with ON CONFLICT DO NOTHING. Returns inserted id or
        None on conflict. Dialect-aware (Postgres + SQLite both support the
        ON CONFLICT clause via their respective `insert()` constructors)."""
        dialect = self.db.bind.dialect.name if self.db.bind is not None else (
            self.db.get_bind().dialect.name
        )
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as dialect_insert
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as dialect_insert
        else:
            raise NotImplementedError(
                f"bulk_upsert/upsert: dialect {dialect!r} not supported"
            )
        stmt = dialect_insert(TransactionCategoryRule).values(**values)
        stmt = stmt.on_conflict_do_nothing(index_elements=[
            TransactionCategoryRule.user_id,
            TransactionCategoryRule.normalized_description,
            TransactionCategoryRule.category_id,
            TransactionCategoryRule.operation_type,
        ]).returning(TransactionCategoryRule.id)
        result = self.db.execute(stmt).scalar()
        return result

    def get_active_legacy_rule(
        self,
        *,
        user_id: int,
        normalized_description: str,
    ) -> TransactionCategoryRule | None:
        """Skeleton-only lookup, third-priority in the cluster service.

        Active rules without an identifier anchor. Same legacy-scope cleanup
        as `get_best_rule`: rules with `scope='bank'` or `'legacy_pattern'`
        are deprecated (PR1) and never participate in matching, even when
        they're still flagged active by an old code path. The post-migration
        scope `general` is the supported skeleton-bound scope.

        We EXCLUDE rules that have a bound identifier_value — those are
        meant to match only their exact identifier (path 1), not any row
        that shares the same skeleton. This is the fix for the «перевод по
        договору» false-green problem.
        """
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.normalized_description == normalized_description,
                TransactionCategoryRule.is_active.is_(True),
                TransactionCategoryRule.identifier_value.is_(None),
                TransactionCategoryRule.scope.in_(tuple(ACTIVE_PREVIEW_SCOPES)),
            )
            .order_by(
                TransactionCategoryRule.confirms.desc(),
                TransactionCategoryRule.updated_at.desc(),
            )
            .first()
        )

    def get_active_rule_by_identifier(
        self,
        *,
        user_id: int,
        identifier_key: str,
        identifier_value: str,
    ) -> TransactionCategoryRule | None:
        """Exact-scope lookup: find an active rule bound to a specific identifier
        (phone/contract/iban/card/person_hash). Used by the Phase 3 clusterer
        to propose a category for a cluster that carries a known identifier."""
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.identifier_key == identifier_key,
                TransactionCategoryRule.identifier_value == identifier_value,
                TransactionCategoryRule.is_active.is_(True),
            )
            .order_by(
                TransactionCategoryRule.confirms.desc(),
                TransactionCategoryRule.updated_at.desc(),
            )
            .first()
        )

    def get_active_rule_by_bank(
        self,
        *,
        user_id: int,
        bank_code: str,
        normalized_description: str,
    ) -> TransactionCategoryRule | None:
        """Bank-scope lookup: find an active generalized rule for a given bank
        and matching normalized description. Used as a secondary signal when
        no exact identifier rule matched."""
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.scope == "bank",
                TransactionCategoryRule.bank_code == bank_code,
                TransactionCategoryRule.normalized_description == normalized_description,
                TransactionCategoryRule.is_active.is_(True),
            )
            .order_by(
                TransactionCategoryRule.confirms.desc(),
                TransactionCategoryRule.updated_at.desc(),
            )
            .first()
        )

    def list_rules(
        self,
        *,
        user_id: int,
        scope: str | None = None,
        is_active: bool | None = None,
    ) -> list[TransactionCategoryRule]:
        q = self.db.query(TransactionCategoryRule).filter(
            TransactionCategoryRule.user_id == user_id
        )
        if scope is not None:
            q = q.filter(TransactionCategoryRule.scope == scope)
        if is_active is not None:
            q = q.filter(TransactionCategoryRule.is_active == is_active)
        return (
            q.order_by(
                TransactionCategoryRule.is_active.desc(),
                TransactionCategoryRule.confirms.desc(),
                TransactionCategoryRule.updated_at.desc(),
            )
            .all()
        )

    def list_with_labels(self, *, user_id: int) -> list[TransactionCategoryRule]:
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.user_label.isnot(None),
                TransactionCategoryRule.user_label != "",
            )
            .order_by(TransactionCategoryRule.confirms.desc(), TransactionCategoryRule.updated_at.desc())
            .all()
        )

    def set_user_label(self, *, rule_id: int, user_id: int, user_label: str | None) -> TransactionCategoryRule | None:
        rule = (
            self.db.query(TransactionCategoryRule)
            .filter(TransactionCategoryRule.id == rule_id, TransactionCategoryRule.user_id == user_id)
            .first()
        )
        if rule is None:
            return None
        rule.user_label = user_label
        self.db.add(rule)
        self.db.flush()
        return rule
