from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BankSupportRequestStatus = Literal["pending", "in_review", "added", "rejected"]


class BankSupportRequestCreate(BaseModel):
    bank_id: int | None = Field(default=None, description="ID банка из /banks, если известен")
    bank_name: str = Field(min_length=1, max_length=255, description="Название банка как ввёл пользователь")
    note: str | None = Field(default=None, max_length=2000, description="Дополнительный комментарий")


class BankSupportRequestResponse(BaseModel):
    id: int
    bank_id: int | None
    bank_name: str
    note: str | None
    status: BankSupportRequestStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}
