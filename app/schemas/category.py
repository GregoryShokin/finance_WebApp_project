
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CategoryKind(str, Enum):
    income = "income"
    expense = "expense"


class CategoryPriority(str, Enum):
    expense_essential = "expense_essential"
    expense_secondary = "expense_secondary"
    expense_target = "expense_target"
    income_active = "income_active"
    income_passive = "income_passive"


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: CategoryKind
    priority: CategoryPriority
    is_system: bool = False
    exclude_from_planning: bool = False
    income_type: Literal["active", "passive"] | None = None


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: CategoryKind | None = None
    priority: CategoryPriority | None = None
    is_system: bool | None = None
    exclude_from_planning: bool | None = None
    income_type: Literal["active", "passive"] | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    kind: CategoryKind
    priority: CategoryPriority
    color: str | None
    icon_name: str
    is_system: bool
    exclude_from_planning: bool
    income_type: Literal["active", "passive"] | None
    created_at: datetime
    updated_at: datetime
