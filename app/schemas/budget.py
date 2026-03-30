from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BudgetProgressResponse(BaseModel):
    category_id: int
    category_name: str
    planned_amount: Decimal
    spent_amount: Decimal
    remaining: Decimal
    percent_used: float


class BudgetUpdateRequest(BaseModel):
    planned_amount: Decimal = Field(ge=0)


class BudgetAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    alert_type: str
    category_id: int | None
    message: str
    triggered_at: datetime
    is_read: bool
