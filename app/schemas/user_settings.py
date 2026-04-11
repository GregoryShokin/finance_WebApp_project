from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserSettingsUpdateRequest(BaseModel):
    large_purchase_threshold_pct: float = Field(
        ge=0.05,
        le=0.50,
        description="Порог крупной покупки: доля от среднемесячных расходов (5%–50%)",
    )


class UserSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    large_purchase_threshold_pct: float
    created_at: datetime | None = None
    updated_at: datetime | None = None
