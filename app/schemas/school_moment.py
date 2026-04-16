from __future__ import annotations

from pydantic import BaseModel


class SchoolMomentResponse(BaseModel):
    id: str
    category: str
    severity: str
    title: str
    message: str
    requires_purchases: bool


class SchoolMomentsListResponse(BaseModel):
    moments: list[SchoolMomentResponse]
