from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.repositories.bank_repository import BankRepository
from pydantic import BaseModel

router = APIRouter(prefix="/banks", tags=["banks"])


class BankResponse(BaseModel):
    id: int
    name: str
    code: str
    bik: str | None
    is_popular: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BankResponse])
def list_banks(
    q: str | None = Query(default=None, description="Поиск по названию"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    repo = BankRepository(db)
    if q and q.strip():
        return repo.search(q)
    return repo.list_all()
