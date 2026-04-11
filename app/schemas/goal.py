from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GoalCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    target_amount: Decimal = Field(gt=0)
    deadline: date | None = None
    category_id: int | None = None


class GoalUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    target_amount: Decimal | None = Field(default=None, gt=0)
    deadline: date | None = None
    category_id: int | None = None


class GoalForecastRequest(BaseModel):
    target_amount: Decimal = Field(gt=0)
    deadline: date | None = None
    monthly_contribution: Decimal | None = Field(default=None, ge=0)


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
    category_id: int | None = None
    created_at: datetime
    updated_at: datetime


class GoalWithProgressResponse(GoalResponse):
    saved: Decimal
    percent: float
    remaining: Decimal
    monthly_needed: Decimal | None
    is_on_track: bool | None = None
    shortfall: Decimal | None = None
    estimated_date: date | None = None


class GoalForecastResponse(BaseModel):
    monthly_avg_balance: Decimal
    monthly_needed: Decimal | None
    estimated_months: int | None
    estimated_date: date | None
    is_achievable: bool
    shortfall: Decimal | None
    suggested_date: date | None
    contribution_percent: Decimal | None
    deadline_too_close: bool = False
