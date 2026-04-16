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


# ── Multi-metric system (Stage 2) ───────────────────────────────────────────


class FlowMetricResponse(BaseModel):
    basic_flow: Decimal
    full_flow: Decimal
    lifestyle_indicator: float | None
    zone: str
    trend: Decimal | None


class CapitalMetricResponse(BaseModel):
    capital: Decimal
    trend: Decimal | None


class DTIMetricResponse(BaseModel):
    dti_percent: float | None
    zone: str | None
    monthly_payments: Decimal
    regular_income: Decimal


class ReserveMetricResponse(BaseModel):
    months: float | None
    zone: str | None
    available_cash: Decimal
    monthly_outflow: Decimal


class MetricsSummaryResponse(BaseModel):
    flow: FlowMetricResponse
    capital: CapitalMetricResponse
    dti: DTIMetricResponse
    reserve: ReserveMetricResponse
    fi_score: float


class HealthRecommendation(BaseModel):
    metric: str
    zone: str
    priority: int
    message_key: str
    title: str
    message: str


class HealthSummaryResponse(BaseModel):
    metrics: MetricsSummaryResponse
    fi_score: float
    fi_zone: str
    weakest_metric: str
    recommendations: list[HealthRecommendation]
