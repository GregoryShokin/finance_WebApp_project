from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository

router = APIRouter(prefix="/category-rules", tags=["Category Rules"])


@router.get("")
def list_category_rules(
    scope: str | None = Query(default=None, description="Filter by scope: exact, bank, global, legacy_pattern"),
    is_active: bool | None = Query(default=None, description="Filter by active/inactive status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = TransactionCategoryRuleRepository(db)
    rules = repo.list_rules(user_id=current_user.id, scope=scope, is_active=is_active)
    return [
        {
            "id": r.id,
            "normalized_description": r.normalized_description,
            "original_description": r.original_description,
            "user_label": r.user_label,
            "category_id": r.category_id,
            "confirms": r.confirms,
            "rejections": r.rejections,
            "scope": r.scope,
            "is_active": r.is_active,
            "bank_code": r.bank_code,
            "account_id_scope": r.account_id_scope,
            "identifier_key": r.identifier_key,
            "identifier_value": r.identifier_value,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rules
    ]
