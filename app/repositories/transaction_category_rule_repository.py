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

    def upsert(self, *, user_id: int, normalized_description: str, category_id: int) -> TransactionCategoryRule:
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
                category_id=category_id,
                hit_count=1,
            )
            self.db.add(rule)
            self.db.flush()
            return rule

        rule.hit_count += 1
        self.db.add(rule)
        self.db.flush()
        return rule
