from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.counterparty import (
    CounterpartyCreateRequest,
    CounterpartyResponse,
    CounterpartyUpdateRequest,
)
from app.services.counterparty_service import (
    CounterpartyNotFoundError,
    CounterpartyService,
    CounterpartyValidationError,
)

router = APIRouter(prefix="/counterparties", tags=["Counterparties"])


@router.get("", response_model=list[CounterpartyResponse])
def list_counterparties(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CounterpartyService(db).list_counterparties(user_id=current_user.id)


@router.post("", response_model=CounterpartyResponse, status_code=status.HTTP_201_CREATED)
def create_counterparty(
    payload: CounterpartyCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CounterpartyService(db)
    try:
        item = service.create_counterparty(user_id=current_user.id, payload=payload.model_dump())
        db.commit()
        db.refresh(item)
        item.receivable_amount = item.opening_receivable_amount
        item.payable_amount = item.opening_payable_amount
        return item
    except CounterpartyValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{counterparty_id}", response_model=CounterpartyResponse)
def update_counterparty(
    counterparty_id: int,
    payload: CounterpartyUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CounterpartyService(db)
    try:
        item = service.update_counterparty(
            user_id=current_user.id,
            counterparty_id=counterparty_id,
            payload=payload.model_dump(exclude_unset=True),
        )
        db.commit()
        db.refresh(item)
        item.receivable_amount = item.opening_receivable_amount
        item.payable_amount = item.opening_payable_amount
        return item
    except CounterpartyNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CounterpartyValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{counterparty_id}")
def delete_counterparty(
    counterparty_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return CounterpartyService(db).delete_counterparty(user_id=current_user.id, counterparty_id=counterparty_id)
    except CounterpartyNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
