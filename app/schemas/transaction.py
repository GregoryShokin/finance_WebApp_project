from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    credit_early_repayment = "credit_early_repayment"
    credit_interest = "credit_interest"
    debt = "debt"
    refund = "refund"
    adjustment = "adjustment"


class TransactionCreateRequest(BaseModel):
    account_id: int
    target_account_id: int | None = None
    credit_account_id: int | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    goal_id: int | None = None
    amount: Decimal = Field(gt=0)
    credit_principal_amount: Decimal | None = Field(default=None, ge=0)
    credit_interest_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    type: TransactionType
    operation_type: TransactionOperationType = TransactionOperationType.regular
    debt_direction: str | None = Field(default=None, pattern="^(lent|borrowed|repaid|collected)?$")
    description: str | None = Field(default=None, max_length=500)
    transaction_date: datetime
    needs_review: bool = False

    # Installment purchase fields (only used when account type is installment_card)
    installment_term_months: int | None = Field(default=None, ge=1, le=120)
    installment_monthly_payment: Decimal | None = Field(default=None, ge=0)
    installment_description: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_credit_payment(self):
        if self.operation_type in {
            TransactionOperationType.credit_payment,
            TransactionOperationType.credit_early_repayment,
        }:
            if self.credit_account_id is None:
                raise ValueError("Для платежа по кредиту нужно указать кредит.")
            if self.operation_type == TransactionOperationType.credit_payment:
                if self.credit_principal_amount is None:
                    raise ValueError("Для платежа по кредиту укажи сумму основного долга.")
                if self.credit_interest_amount is None:
                    raise ValueError("Для платежа по кредиту укажи сумму процентов.")
                if (self.credit_principal_amount + self.credit_interest_amount) != self.amount:
                    raise ValueError("Сумма платежа должна быть равна сумме основного долга и процентов.")
            elif self.operation_type == TransactionOperationType.credit_early_repayment:
                if self.credit_principal_amount is None:
                    raise ValueError("Для досрочного погашения укажи сумму основного долга.")
        return self


class TransactionUpdateRequest(BaseModel):
    account_id: int | None = None
    target_account_id: int | None = None
    credit_account_id: int | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    goal_id: int | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    credit_principal_amount: Decimal | None = Field(default=None, ge=0)
    credit_interest_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    type: TransactionType | None = None
    operation_type: TransactionOperationType | None = None
    debt_direction: str | None = Field(default=None, pattern="^(lent|borrowed|repaid|collected)?$")
    description: str | None = Field(default=None, max_length=500)
    transaction_date: datetime | None = None
    needs_review: bool | None = None

    # Installment purchase fields (only used when account type is installment_card)
    installment_term_months: int | None = Field(default=None, ge=1, le=120)
    installment_monthly_payment: Decimal | None = Field(default=None, ge=0)
    installment_description: str | None = Field(default=None, max_length=255)


class TransactionSplitItemRequest(BaseModel):
    category_id: int
    amount: Decimal = Field(gt=0)
    debt_direction: str | None = Field(default=None, pattern="^(lent|borrowed|repaid|collected)?$")
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
    credit_account_id: int | None
    transfer_pair_id: int | None = None
    goal_id: int | None = None
    category_id: int | None
    counterparty_id: int | None
    category_priority: CategoryPriority | None = None
    amount: Decimal
    credit_principal_amount: Decimal | None
    credit_interest_amount: Decimal | None
    debt_direction: str | None
    currency: str
    type: TransactionType
    operation_type: TransactionOperationType
    counterparty_name: str | None = None
    description: str | None
    normalized_description: str | None
    transaction_date: datetime
    needs_review: bool
    affects_analytics: bool
    is_regular: bool
    converted_to_installment: bool
    # Installment purchase data (populated from linked InstallmentPurchase)
    installment_term_months: int | None = None
    installment_monthly_payment: Decimal | None = None
    installment_description: str | None = None
    created_at: datetime
    updated_at: datetime
