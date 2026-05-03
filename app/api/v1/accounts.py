from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.account import (
    AccountCreateRequest,
    AccountResponse,
    AccountUpdateRequest,
    BalanceAdjustRequest,
    CloseAccountRequest,
)
from app.services.account_service import (
    AccountNotFoundError,
    AccountService,
    BankRequiredError,
    CloseAccountValidationError,
)

router = APIRouter(prefix="/accounts", tags=["Accounts"])


def _prepare_payload(data: dict) -> dict:
    if "currency" in data and data["currency"] is not None:
        data["currency"] = str(data["currency"]).upper()
    return data


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    data = _prepare_payload(payload.model_dump(exclude_unset=True, by_alias=False))
    data["user_id"] = current_user.id
    try:
        return AccountService(db).create(**data)
    except BankRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("", response_model=list[AccountResponse])
def list_accounts(
    include_closed: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the user's accounts.

    By default closed accounts (spec §13, v1.20) are excluded — they're for
    history and moderator-side workflows only. Pass `?include_closed=true`
    to fetch all accounts (used by the moderator's account-selector and the
    «Закрытые счета» section on the accounts page).
    """
    return AccountService(db).list_with_last_transaction(
        user_id=current_user.id, include_closed=include_closed,
    )


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return AccountService(db).get(account_id=account_id, user_id=current_user.id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, payload: AccountUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        data = _prepare_payload(payload.model_dump(exclude_unset=True, by_alias=False))
        return AccountService(db).update(account_id=account_id, user_id=current_user.id, **data)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BankRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except CloseAccountValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{account_id}/close", response_model=AccountResponse)
def close_account(
    account_id: int,
    payload: CloseAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an account as closed (spec §13, v1.20).

    Validation: closed_at must not be in the future and must be ≥ the latest
    transaction date on this account. Atomically flips is_active=False.
    Existing transactions stay; balance is NOT auto-zeroed.
    """
    try:
        return AccountService(db).close(
            account_id=account_id,
            user_id=current_user.id,
            closed_at=payload.closed_at,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CloseAccountValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{account_id}/reopen", response_model=AccountResponse)
def reopen_account(
    account_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-open a previously closed account (spec §13, v1.20)."""
    try:
        return AccountService(db).reopen(
            account_id=account_id, user_id=current_user.id,
        )
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CloseAccountValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        AccountService(db).delete(account_id=account_id, user_id=current_user.id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{account_id}/adjust", status_code=status.HTTP_200_OK)
def adjust_account_balance(
    account_id: int,
    payload: BalanceAdjustRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        AccountService(db).adjust_balance(
            account_id=account_id,
            user_id=current_user.id,
            target_balance=payload.target_balance,
            comment=payload.comment,
        )
        return {"ok": True}
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
