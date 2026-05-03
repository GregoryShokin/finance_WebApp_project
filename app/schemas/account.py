from datetime import date, datetime
from decimal import Decimal

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


AccountType = Literal[
    'main',             # обычный дебетовый
    'cash',             # наличный счёт (без привязки к банку)
    'marketplace',      # маркетплейсовый кошелёк (Ozon, WB, …)
    'loan',             # потребительский кредит
    'credit_card',      # кредитная карта
    'installment_card', # карта рассрочки (Халва, Сплит)
    'broker',           # брокерский счёт
    'savings',          # вклад (срочный, с датами и капитализацией)
    'savings_account',  # накопительный счёт (бессрочный, только ставка)
    'currency',         # валютный счёт
]


class BankRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    bik: str | None = None
    is_popular: bool


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    balance: Decimal = Field(default=0)
    is_active: bool = True
    account_type: AccountType = "main"
    is_credit: bool = False
    # Bank is optional only for cash accounts (no statement extractor needed).
    # All other account types require a bank for statement parsing.
    bank_id: int | None = Field(default=None, ge=1)

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

    @model_validator(mode='after')
    def validate_bank_and_loan(self) -> 'AccountCreateRequest':
        if self.account_type != 'cash' and self.bank_id is None:
            raise ValueError('Банк обязателен для всех счетов, кроме наличных')
        return self

    @model_validator(mode='after')
    def validate_loan_requires_params(self) -> 'AccountCreateRequest':
        if self.account_type == 'loan':
            missing = [
                f for f, v in [
                    ('credit_limit_original', self.credit_limit_original),
                    ('credit_current_amount', self.credit_current_amount),
                    ('credit_interest_rate', self.credit_interest_rate),
                    ('credit_term_remaining', self.credit_term_remaining),
                ]
                if v is None
            ]
            if missing:
                raise ValueError(
                    f"Для кредитного счёта обязательны поля: {', '.join(missing)}"
                )
        return self


class AccountUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    balance: Decimal | None = None
    is_active: bool | None = None
    account_type: AccountType | None = None
    is_credit: bool | None = None
    bank_id: int | None = None

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
    bank_id: int
    bank: BankRef | None = None
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
