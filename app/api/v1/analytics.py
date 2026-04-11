from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.transaction import LargePurchasesListResponse, TransactionResponse
from app.services.financial_health_service import FinancialHealthService

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get(
    "/large-purchases",
    response_model=LargePurchasesListResponse,
    status_code=status.HTTP_200_OK,
)
def get_large_purchases(
    months: int = Query(default=6, ge=1, le=24, description="Количество месяцев для выборки"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return large and deferred purchases for the last N months.

    Includes:
    - Deferred credit/installment purchases (is_deferred_purchase=True)
    - Free-cash large purchases (is_large_purchase=True)
    """
    service = FinancialHealthService(db)
    result = service.get_large_purchases(user_id=current_user.id, months=months)
    return LargePurchasesListResponse(
        transactions=[TransactionResponse.model_validate(tx) for tx in result["transactions"]],
        total_amount=result["total_amount"],
        months=result["months"],
    )
