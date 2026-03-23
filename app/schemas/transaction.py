from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.category import CategoryPriority


class TransactionType(str, Enum):
    income = "income"
    expense = "expense"


class TransactionOperationType(str, Enum):
    regular = "regular"
    transfer = "transfer"
    investment_buy = "investment_buy"
    investment_sell = "investment_sell"
    credit_disbursement = "credit_disbursement"
    credit_payment = "credit_payment"
    credit_interest = "credit_interest"
    debt = "debt"
    refund = "refund"
    adjustment = "adjustment"


class TransactionCreateRequest(BaseModel):
    account_id: int
    target_account_id: int | None = None
    category_id: int | None = None
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    type: TransactionType
    operation_type: TransactionOperationType = TransactionOperationType.regular
    description: str | None = Field(default=None, max_length=500)
    transaction_date: datetime
    needs_review: bool = False


class TransactionUpdateRequest(BaseModel):
    account_id: int | None = None
    target_account_id: int | None = None
    category_id: int | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    type: TransactionType | None = None
    operation_type: TransactionOperationType | None = None
    description: str | None = Field(default=None, max_length=500)
    transaction_date: datetime | None = None
    needs_review: bool | None = None


class TransactionSplitItemRequest(BaseModel):
    category_id: int
    amount: Decimal = Field(gt=0)
    description: str | None = Field(default=None, max_length=500)


class TransactionSplitRequest(BaseModel):
    items: list[TransactionSplitItemRequest] = Field(min_length=2)


class TransactionDeletePeriodRequest(BaseModel):
    date_from: datetime
    date_to: datetime
    account_id: int | None = None


class TransactionDeletePeriodResponse(BaseModel):
    deleted_count: int


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    account_id: int
    target_account_id: int | None
    category_id: int | None
    category_priority: CategoryPriority | None = None
    amount: Decimal
    currency: str
    type: TransactionType
    operation_type: TransactionOperationType
    description: str | None
    normalized_description: str | None
    transaction_date: datetime
    needs_review: bool
    affects_analytics: bool
    created_at: datetime
    updated_at: datetime
