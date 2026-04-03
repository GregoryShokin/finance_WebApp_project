from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GoalCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    target_amount: Decimal = Field(gt=0)
    deadline: date | None = None


class GoalUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    target_amount: Decimal | None = Field(default=None, gt=0)
    deadline: date | None = None


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    target_amount: Decimal
    deadline: date | None
    status: str
    is_system: bool
    system_key: str | None
    created_at: datetime
    updated_at: datetime


class GoalWithProgressResponse(GoalResponse):
    saved: Decimal
    percent: float
    remaining: Decimal
    monthly_needed: Decimal | None