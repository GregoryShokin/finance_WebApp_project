from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.transaction_category_rule import TransactionCategoryRule


class TransactionCategoryRuleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_best_rule(self, *, user_id: int, normalized_description: str) -> TransactionCategoryRule | None:
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.normalized_description == normalized_description,
            )
            .order_by(TransactionCategoryRule.hit_count.desc(), TransactionCategoryRule.updated_at.desc(), TransactionCategoryRule.id.desc())
            .first()
        )

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
                hit_count=1,
            )
            self.db.add(rule)
            self.db.flush()
            return rule

        rule.hit_count += 1
        if original_description and not rule.original_description:
            rule.original_description = original_description
        if user_label is not None:
            rule.user_label = user_label
        self.db.add(rule)
        self.db.flush()
        return rule

    def list_with_labels(self, *, user_id: int) -> list[TransactionCategoryRule]:
        return (
            self.db.query(TransactionCategoryRule)
            .filter(
                TransactionCategoryRule.user_id == user_id,
                TransactionCategoryRule.user_label.isnot(None),
                TransactionCategoryRule.user_label != "",
            )
            .order_by(TransactionCategoryRule.hit_count.desc(), TransactionCategoryRule.updated_at.desc())
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
