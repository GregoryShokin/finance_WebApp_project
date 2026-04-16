from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class InstallmentDetail(BaseModel):
    description: str
    monthly_payment: Decimal
    remaining_months: int


class InstallmentAnnotation(BaseModel):
    description: str
    category_name: str | None
    monthly_payment: Decimal
    original_amount: Decimal
    remaining_amount: Decimal
    started_this_month: bool


class CategoryExpense(BaseModel):
    category_id: int | None
    category_name: str
    amount: Decimal
    is_regular: bool
    installment_details: list[InstallmentDetail] | None = None


class InstallmentAccountSummary(BaseModel):
    account_name: str
    total_debt: Decimal
    monthly_payment: Decimal | None = None
    has_purchase_details: bool


class ExpenseAnalyticsResponse(BaseModel):
    total_expenses: Decimal
    regular_expenses: Decimal
    irregular_expenses: Decimal
    categories: list[CategoryExpense]
    installment_annotations: list[InstallmentAnnotation]
    new_installment_obligations: Decimal
    installment_accounts_summary: list[InstallmentAccountSummary] = []
