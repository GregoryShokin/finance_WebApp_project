from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class InstallmentPurchaseStatus(str, Enum):
    active = "active"
    completed = "completed"
    early_closed = "early_closed"


class InstallmentPurchaseCreateRequest(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    category_id: int | None = None
    transaction_id: int | None = None
    original_amount: Decimal = Field(gt=0)
    interest_rate: Decimal = Field(ge=0, default=0)
    term_months: int = Field(gt=0)
    monthly_payment: Decimal = Field(gt=0)
    start_date: date


class InstallmentPurchaseUpdateRequest(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=255)
    category_id: int | None = None
    remaining_amount: Decimal | None = Field(default=None, ge=0)
    status: InstallmentPurchaseStatus | None = None


class InstallmentPurchaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    transaction_id: int | None
    category_id: int | None
    description: str
    original_amount: Decimal
    remaining_amount: Decimal
    interest_rate: Decimal
    term_months: int
    monthly_payment: Decimal
    start_date: date
    status: InstallmentPurchaseStatus
    created_at: datetime
    updated_at: datetime


class InstallmentPurchaseListResponse(BaseModel):
    items: list[InstallmentPurchaseResponse]
    warning: str | None = None
