from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DebtPartnerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    opening_balance: Decimal = Field(default=0, ge=0)
    opening_balance_kind: str = Field(
        default="receivable", pattern="^(receivable|payable)$"
    )
    note: str | None = Field(default=None, max_length=500)


class DebtPartnerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    opening_receivable_amount: Decimal
    opening_payable_amount: Decimal
    receivable_amount: Decimal = Decimal("0")
    payable_amount: Decimal = Decimal("0")
    note: str | None = None
    created_at: datetime
    updated_at: datetime
