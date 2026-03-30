from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository

router = APIRouter(prefix="/category-rules", tags=["Category Rules"])


@router.get("")
def list_category_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = TransactionCategoryRuleRepository(db)
    rules = repo.list_with_labels(user_id=current_user.id)
    return [
        {
            "id": r.id,
            "normalized_description": r.normalized_description,
            "original_description": r.original_description,
            "user_label": r.user_label,
            "category_id": r.category_id,
            "hit_count": r.hit_count,
        }
        for r in rules
    ]
