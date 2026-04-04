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


class ChronicViolation(BaseModel):
    category_name: str
    months_count: int
    overage_percent: float


class FinancialHealthResponse(BaseModel):
    savings_rate: float
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

    fi_percent: float
    fi_zone: str
    fi_capital_needed: float
    fi_passive_income: float

    fi_score: float
    fi_score_zone: str
    fi_score_components: dict[str, float | int | str | None | dict[str, float]]
