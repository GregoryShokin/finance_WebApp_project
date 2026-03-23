from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.account import AccountCreateRequest, AccountResponse, AccountUpdateRequest
from app.services.account_service import AccountNotFoundError, AccountService

router = APIRouter(prefix="/accounts", tags=["Accounts"])


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return AccountService(db).create(
        user_id=current_user.id,
        name=payload.name,
        currency=payload.currency.upper(),
        balance=payload.balance,
        is_active=payload.is_active,
        is_credit=payload.is_credit,
    )


@router.get("", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return AccountService(db).list(user_id=current_user.id)


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        return AccountService(db).get(account_id=account_id, user_id=current_user.id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, payload: AccountUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        data = payload.model_dump(exclude_unset=True)
        if "currency" in data and data["currency"] is not None:
            data["currency"] = data["currency"].upper()
        return AccountService(db).update(account_id=account_id, user_id=current_user.id, **data)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        AccountService(db).delete(account_id=account_id, user_id=current_user.id)
    except AccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
