from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.repositories.bank_repository import BankRepository

router = APIRouter(prefix="/banks", tags=["banks"])


ExtractorStatus = Literal["supported", "in_review", "pending", "broken"]


class BankResponse(BaseModel):
    id: int
    name: str
    code: str
    bik: str | None
    is_popular: bool
    extractor_status: ExtractorStatus
    extractor_last_tested_at: date | None = None
    extractor_notes: str | None = None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BankResponse])
def list_banks(
    q: str | None = Query(default=None, description="Поиск по названию"),
    supported_only: bool = Query(
        default=False,
        description="Вернуть только банки с протестированным экстрактором импорта",
    ),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    repo = BankRepository(db)
    if q and q.strip():
        return repo.search(q, supported_only=supported_only)
    return repo.list_all(supported_only=supported_only)
