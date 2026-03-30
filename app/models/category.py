
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CategoryKind(str, Enum):
    income = "income"
    expense = "expense"


class CategoryPriority(str, Enum):
    expense_essential = "expense_essential"
    expense_secondary = "expense_secondary"
    expense_target = "expense_target"
    income_active = "income_active"
    income_passive = "income_passive"


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CategoryPriority.expense_essential.value,
        server_default=CategoryPriority.expense_essential.value,
        index=True,
    )
    color: Mapped[str | None] = mapped_column(String(32), nullable=True)
    icon_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default='tag',
        server_default='tag',
    )
    is_system: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="categories")
    transactions = relationship("Transaction", back_populates="category")
    budgets = relationship("Budget", back_populates="category")
    budget_alerts = relationship("BudgetAlert", back_populates="category")
