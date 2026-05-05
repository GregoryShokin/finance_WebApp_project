"""Isolated bank-support-request router (Этап 1.4 MVP launch).

Lives outside app/api/v1/imports.py on purpose: Stage 0 is rewriting the
imports router in parallel, and we don't want a merge conflict on every
endpoint addition. Bank support requests are a separate resource from
imports anyway — the import flow only reads them indirectly via the
upload-guard error response.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.repositories.bank_repository import BankRepository
from app.repositories.bank_support_request_repository import BankSupportRequestRepository
from app.schemas.bank_support_request import (
    BankSupportRequestCreate,
    BankSupportRequestResponse,
)

router = APIRouter(prefix="/bank-support", tags=["bank-support"])


@router.post(
    "/request",
    response_model=BankSupportRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: BankSupportRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record a request for import support of a specific bank.

    JSON-only payload. Sample-file uploads are deferred (PII / encryption /
    cleanup not in MVP scope — see migration 0061 docstring).

    Idempotent: if the user already has an open ('pending' or 'in_review')
    request for this bank, return that one instead of creating a duplicate.
    """
    repo = BankSupportRequestRepository(db)

    bank_name = payload.bank_name.strip()
    bank_id = payload.bank_id
    if bank_id is not None:
        bank = BankRepository(db).get_by_id(bank_id)
        if bank is not None:
            # Prefer the canonical name from `banks` over user input.
            bank_name = bank.name
        else:
            bank_id = None  # ignore unknown id

    existing = repo.find_open_for_user_and_bank(
        user_id=current_user.id, bank_id=bank_id, bank_name=bank_name,
    )
    if existing is not None:
        return existing

    return repo.create(
        user_id=current_user.id,
        bank_name=bank_name,
        bank_id=bank_id,
        note=payload.note,
    )


@router.get("/requests", response_model=list[BankSupportRequestResponse])
def list_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the current user's bank-support requests, newest first."""
    return BankSupportRequestRepository(db).list_for_user(current_user.id)
