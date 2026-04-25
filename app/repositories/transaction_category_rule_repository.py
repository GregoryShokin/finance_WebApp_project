from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.transaction_category_rule import (
    ACTIVE_PREVIEW_SCOPES,
    TransactionCategoryRule,
)


class TransactionCategoryRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_best_rule(self, *, user_id: int, normalized_description: str) -> TransactionCategoryRule | None:
        """Return the highest-confidence matching rule for skeleton-based
        preview lookup. §6.5 + PR1 cleanup: only `is_active=True` rules
        with one of the post-migration scopes (`specific`, `general`) are
        eligible. Legacy `bank` / `legacy_pattern` rules stay in the table
        per §11.3 (history, possible review) but never silently apply.
        Inactive rules also never match — even if they share a skeleton.
        """
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.normalized_description == normalized_description,
                TransactionCategoryRule.is_active.is_(True),
                TransactionCategoryRule.scope.in_(tuple(ACTIVE_PREVIEW_SCOPES)),
            )
            .order_by(TransactionCategoryRule.confirms.desc(), TransactionCategoryRule.updated_at.desc(), TransactionCategoryRule.id.desc())
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
    ) -> tuple[TransactionCategoryRule, bool]:
        """Find-or-create a rule and set its confirms count in one shot.

        Used by the bulk-cluster moderator action — one UI click validates N
        rows, so the rule should jump straight to `confirms = N` on creation
        (or `+= N` on an existing rule). Returns `(rule, is_new)`.

        Strength-level side effects (activation / generalization) stay in
        `RuleStrengthService.on_confirmed(confirms_delta=N-1)`, which the
        caller invokes after this. We flush but don't commit — the caller
        owns the transaction.
        """
        if confirms_delta < 1:
            raise ValueError(f"confirms_delta must be >= 1, got {confirms_delta}")
        rule = (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.normalized_description == normalized_description,
                TransactionCategoryRule.category_id == category_id,
            )
            .first()
        )
        if rule is None:
            rule = TransactionCategoryRule(
                user_id=user_id,
                normalized_description=normalized_description,
                original_description=original_description,
                category_id=category_id,
                confirms=0,  # on_confirmed will apply the delta
            )
            self.db.add(rule)
            self.db.flush()
            return rule, True
        if original_description and not rule.original_description:
            rule.original_description = original_description
            self.db.add(rule)
            self.db.flush()
        return rule, False

    def upsert(self, *, user_id: int, normalized_description: str, category_id: int, original_description: str | None = None, user_label: str | None = None) -> TransactionCategoryRule:
        rule = (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.normalized_description == normalized_description,
                TransactionCategoryRule.category_id == category_id,
            )
            .first()
        )
        if rule is None:
            rule = TransactionCategoryRule(
                user_id=user_id,
                normalized_description=normalized_description,
                original_description=original_description,
                user_label=user_label,
                category_id=category_id,
                confirms=1,
            )
            self.db.add(rule)
            self.db.flush()
            return rule

        rule.confirms += 1
        if original_description and not rule.original_description:
            rule.original_description = original_description
        if user_label is not None:
            rule.user_label = user_label
        self.db.add(rule)
        self.db.flush()
        return rule

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
