from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ── RealAsset ─────────────────────────────────────────────────────────────────

class RealAssetCreate(BaseModel):
    asset_type: str = Field(max_length=32)
    name: str = Field(max_length=255)
    estimated_value: Decimal = Field(ge=0)


class RealAssetUpdate(BaseModel):
    asset_type: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, max_length=255)
    estimated_value: Decimal | None = Field(default=None, ge=0)


class RealAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_type: str
    name: str
    estimated_value: Decimal
    updated_at: datetime


# ── Financial Health ──────────────────────────────────────────────────────────

class DebtRatioInfo(BaseModel):
    value: float
    status: str
    total_debt: Decimal
    total_assets: Decimal


class FinancialHealthResponse(BaseModel):
    dti_value: float
    dti_status: str
    debt_ratio_basic: DebtRatioInfo
    debt_ratio_extended: DebtRatioInfo | None
