from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.installment_purchase import (
    InstallmentPurchaseCreateRequest,
    InstallmentPurchaseListResponse,
    InstallmentPurchaseResponse,
    InstallmentPurchaseUpdateRequest,
)
from app.services.installment_purchase_service import (
    InstallmentPurchaseNotFoundError,
    InstallmentPurchaseService,
    InstallmentPurchaseValidationError,
)

router = APIRouter(tags=["Installment Purchases"])


@router.get(
    "/accounts/{account_id}/installment-purchases",
    response_model=InstallmentPurchaseListResponse,
)
def list_purchases(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InstallmentPurchaseService(db)
    try:
        items, warning = svc.list_purchases(account_id=account_id, user_id=current_user.id)
    except InstallmentPurchaseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return InstallmentPurchaseListResponse(
        items=[InstallmentPurchaseResponse.model_validate(p) for p in items],
        warning=warning,
    )


@router.post(
    "/accounts/{account_id}/installment-purchases",
    response_model=InstallmentPurchaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_purchase(
    account_id: int,
    payload: InstallmentPurchaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InstallmentPurchaseService(db)
    data = payload.model_dump()
    try:
        purchase, _warning = svc.create_purchase(
            account_id=account_id, user_id=current_user.id, data=data
        )
    except InstallmentPurchaseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return purchase


@router.get(
    "/accounts/{account_id}/installment-purchases/{purchase_id}",
    response_model=InstallmentPurchaseResponse,
)
def get_purchase(
    account_id: int,
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InstallmentPurchaseService(db)
    try:
        return svc.get_purchase(purchase_id=purchase_id, user_id=current_user.id)
    except InstallmentPurchaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put(
    "/accounts/{account_id}/installment-purchases/{purchase_id}",
    response_model=InstallmentPurchaseResponse,
)
def update_purchase(
    account_id: int,
    purchase_id: int,
    payload: InstallmentPurchaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InstallmentPurchaseService(db)
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is not None:
        updates["status"] = updates["status"].value
    try:
        purchase, _warning = svc.update_purchase(
            purchase_id=purchase_id, user_id=current_user.id, updates=updates
        )
    except InstallmentPurchaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InstallmentPurchaseValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return purchase


@router.delete(
    "/accounts/{account_id}/installment-purchases/{purchase_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_purchase(
    account_id: int,
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InstallmentPurchaseService(db)
    try:
        svc.delete_purchase(purchase_id=purchase_id, user_id=current_user.id)
    except InstallmentPurchaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
