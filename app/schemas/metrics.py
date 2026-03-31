from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class FinancialIndependenceMetricResponse(BaseModel):
    percent: float
    passive_income: Decimal
    avg_expenses: Decimal
    gap: Decimal
    months_of_data: int


class SavingsRateMetricResponse(BaseModel):
    percent: float
    invested: Decimal
    total_income: Decimal


class MetricsResponse(BaseModel):
    financial_independence: FinancialIndependenceMetricResponse | None
    savings_rate: SavingsRateMetricResponse
