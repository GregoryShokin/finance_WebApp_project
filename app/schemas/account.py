from datetime import date, datetime
from decimal import Decimal

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


AccountType = Literal['regular', 'credit', 'credit_card', 'cash', 'broker', 'deposit', 'installment_card']


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    balance: Decimal = Field(default=0)
    is_active: bool = True
    account_type: AccountType = "regular"
    is_credit: bool = False

    credit_limit_original: Decimal | None = None
    credit_current_amount: Decimal | None = None
    credit_interest_rate: Decimal | None = None
    credit_term_remaining: int | None = None
    monthly_payment: Decimal | None = None
    deposit_interest_rate: Decimal | None = None
    deposit_open_date: date | None = None
    deposit_close_date: date | None = None
    deposit_capitalization_period: str | None = None
    contract_number: str | None = None
    statement_account_number: str | None = None


class AccountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    balance: Decimal | None = None
    is_active: bool | None = None
    account_type: AccountType | None = None
    is_credit: bool | None = None

    credit_limit_original: Decimal | None = None
    credit_current_amount: Decimal | None = None
    credit_interest_rate: Decimal | None = None
    credit_term_remaining: int | None = None
    monthly_payment: Decimal | None = None
    deposit_interest_rate: Decimal | None = None
    deposit_open_date: date | None = None
    deposit_close_date: date | None = None
    deposit_capitalization_period: str | None = None
    contract_number: str | None = None
    statement_account_number: str | None = None


class BalanceAdjustRequest(BaseModel):
    target_balance: Decimal
    comment: str | None = Field(default=None, max_length=255)


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    currency: str
    balance: Decimal
    is_active: bool
    account_type: AccountType
    is_credit: bool
    credit_limit_original: Decimal | None = None
    credit_current_amount: Decimal | None = None
    credit_interest_rate: Decimal | None = None
    credit_term_remaining: int | None = None
    monthly_payment: Decimal | None = None
    deposit_interest_rate: Decimal | None = None
    deposit_open_date: date | None = None
    deposit_close_date: date | None = None
    deposit_capitalization_period: str | None = None
    contract_number: str | None = None
    statement_account_number: str | None = None
    last_transaction_date: datetime | None = None
    created_at: datetime
    updated_at: datetime
