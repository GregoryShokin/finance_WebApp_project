from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.debt_partner import DebtPartnerCreateRequest, DebtPartnerResponse
from app.services.debt_partner_service import (
    DebtPartnerNotFoundError,
    DebtPartnerService,
    DebtPartnerValidationError,
)

router = APIRouter(prefix="/debt-partners", tags=["Debt partners"])


@router.get("", response_model=list[DebtPartnerResponse])
def list_debt_partners(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return DebtPartnerService(db).list_partners(user_id=current_user.id)


@router.post("", response_model=DebtPartnerResponse, status_code=status.HTTP_201_CREATED)
def create_debt_partner(
    payload: DebtPartnerCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = DebtPartnerService(db)
    try:
        item = service.create_partner(
            user_id=current_user.id, payload=payload.model_dump()
        )
        db.commit()
        db.refresh(item)
        item.receivable_amount = item.opening_receivable_amount
        item.payable_amount = item.opening_payable_amount
        return item
    except DebtPartnerValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete("/{partner_id}")
def delete_debt_partner(
    partner_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return DebtPartnerService(db).delete_partner(
            user_id=current_user.id, partner_id=partner_id
        )
    except DebtPartnerNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
