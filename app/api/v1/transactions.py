from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.category import CategoryPriority
from app.schemas.transaction import (
    LargePurchaseCheckResponse,
    TransactionCreateRequest,
    TransactionDeletePeriodRequest,
    TransactionDeletePeriodResponse,
    TransactionOperationType,
    TransactionResponse,
    TransactionSplitRequest,
    TransactionType,
    TransactionUpdateRequest,
)
from app.services.transaction_service import (
    TransactionConflictError,
    TransactionNotFoundError,
    TransactionService,
    TransactionValidationError,
)

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.get("", response_model=list[TransactionResponse])
def list_transactions(
    account_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    category_priority: CategoryPriority | None = Query(default=None),
    type: TransactionType | None = Query(default=None),
    operation_type: TransactionOperationType | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    min_amount: float | None = Query(default=None),
    max_amount: float | None = Query(default=None),
    needs_review: bool | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    return service.list_transactions(
        user_id=current_user.id,
        account_id=account_id,
        category_id=category_id,
        category_priority=category_priority.value if category_priority else None,
        type=type.value if type else None,
        operation_type=operation_type.value if operation_type else None,
        date_from=date_from,
        date_to=date_to,
        min_amount=min_amount,
        max_amount=max_amount,
        needs_review=needs_review,
    )


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    payload: TransactionCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    data = payload.model_dump()
    data["type"] = payload.type.value
    data["operation_type"] = payload.operation_type.value
    try:
        return service.create_transaction(user_id=current_user.id, payload=data)
    except TransactionValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TransactionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/large-purchase-check", response_model=LargePurchaseCheckResponse)
def large_purchase_check(
    amount: Decimal = Query(..., gt=0, description="Сумма предполагаемой покупки"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check whether an amount qualifies as a large purchase for the current user."""
    service = TransactionService(db)
    return service.check_large_purchase(user_id=current_user.id, amount=amount)


@router.put("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(
    transaction_id: int,
    payload: TransactionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    updates = payload.model_dump(exclude_unset=True)
    if "type" in updates and updates["type"] is not None:
        updates["type"] = updates["type"].value
    if "operation_type" in updates and updates["operation_type"] is not None:
        updates["operation_type"] = updates["operation_type"].value
    try:
        return service.update_transaction(user_id=current_user.id, transaction_id=transaction_id, updates=updates)
    except TransactionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TransactionValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TransactionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{transaction_id}", status_code=status.HTTP_200_OK)
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    try:
        service.delete_transaction(user_id=current_user.id, transaction_id=transaction_id)
        return {"success": True}
    except TransactionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TransactionValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TransactionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/delete-period", response_model=TransactionDeletePeriodResponse)
def delete_transactions_by_period(
    payload: TransactionDeletePeriodRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    try:
        deleted_count = service.delete_transactions_by_period(
            user_id=current_user.id,
            date_from=payload.date_from,
            date_to=payload.date_to,
            account_id=payload.account_id,
        )
        return TransactionDeletePeriodResponse(deleted_count=deleted_count)
    except TransactionValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/{transaction_id}/split", response_model=list[TransactionResponse], status_code=status.HTTP_201_CREATED)
def split_transaction(
    transaction_id: int,
    payload: TransactionSplitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = TransactionService(db)
    try:
        return service.split_transaction(
            user_id=current_user.id,
            transaction_id=transaction_id,
            items=[item.model_dump() for item in payload.items],
        )
    except TransactionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TransactionValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TransactionConflictError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
