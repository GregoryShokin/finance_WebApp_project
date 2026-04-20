from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class RealAssetCreate(BaseModel):
    asset_type: str = Field(max_length=32)
    name: str = Field(max_length=255)
    estimated_value: Decimal = Field(ge=0)
    linked_account_id: int | None = None


class RealAssetUpdate(BaseModel):
    asset_type: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=255)
    estimated_value: Decimal | None = Field(default=None, ge=0)
    linked_account_id: int | None = None


class RealAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str
    name: str
    estimated_value: Decimal
    linked_account_id: int | None
    updated_at: datetime


class CapitalHistoryPoint(BaseModel):
    month: str
    label: str
    liquid: float
    deposit: float
    broker: float
    receivable: float
    real_assets: float
    credit_debt: float
    counterparty_debt: float
    total_debt: float
    liquid_capital: float
    net_capital: float


class ChronicViolation(BaseModel):
    category_name: str
    months_count: int
    overage_percent: float


class ChronicUnderperformer(BaseModel):
    category_id: int
    category_name: str
    direction: str
    direction_label: str
    months_count: int
    avg_fulfillment: float
    trend: str
    last_planned: float
    last_actual: float


class UnplannedCategory(BaseModel):
    category_id: int
    category_name: str
    direction: str
    direction_label: str
    avg_monthly_amount: float
    months_with_spending: int


class FIScoreHistory(BaseModel):
    current: float
    previous: float
    baseline: float


class FIScoreComponents(BaseModel):
    # v1.4 weights (2026-04-19): 0.20 + 0.30 + 0.25 + 0.25 = 1.00
    savings_rate: float        # weight 0.20 — normalised basic flow / regular income
    capital_trend: float       # weight 0.30 — capital trajectory (3-month trend)
    dti_inverse: float         # weight 0.25 — 10 - DTI%/6
    buffer_stability: float    # weight 0.25 — deposit months / 6 * 10
    months_calculated: int | None = None
    history: FIScoreHistory | None = None


class DirectionHeatmapRow(BaseModel):
    direction: str
    label: str
    planned: float
    actual: float
    fulfillment: float


class MonthlyHealthSnapshot(BaseModel):
    month: str
    label: str
    income: float
    essential: float
    secondary: float
    planned_income: float
    actual_income: float
    planned_expenses: float
    actual_expenses: float
    savings: float
    savings_rate: float
    essential_rate: float
    secondary_rate: float
    dti: float
    fi_score: float
    discipline: float | None
    direction_heatmap: list[DirectionHeatmapRow]


class FinancialHealthResponse(BaseModel):
    savings_rate: float
    avg_savings_rate: float = 0.0
    savings_rate_zone: str

    monthly_avg_balance: float
    months_calculated: int

    daily_limit: float
    daily_limit_with_carry: float
    carry_over_days: float

    dti: float
    dti_zone: str
    dti_total_payments: float
    dti_income: float

    leverage: float
    leverage_zone: str
    leverage_total_debt: float
    leverage_own_capital: float
    real_assets_total: float = 0.0

    discipline: float | None
    discipline_zone: str | None
    discipline_violations: list[ChronicViolation]
    chronic_underperformers: list[ChronicUnderperformer] = []
    unplanned_categories: list[UnplannedCategory] = []

    fi_percent: float
    fi_zone: str
    fi_capital_needed: float
    fi_passive_income: float
    fi_monthly_gap: float = 0.0

    fi_score: float
    fi_score_zone: str
    fi_score_components: FIScoreComponents
    monthly_history: list[MonthlyHealthSnapshot] = []
