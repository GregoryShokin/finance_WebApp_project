
from datetime import datetime
from enum import Enum

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
    color: str | None = Field(default=None, max_length=32)
    is_system: bool = False


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: CategoryKind | None = None
    priority: CategoryPriority | None = None
    color: str | None = Field(default=None, max_length=32)
    is_system: bool | None = None


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    kind: CategoryKind
    priority: CategoryPriority
    color: str | None
    is_system: bool
    created_at: datetime
    updated_at: datetime
