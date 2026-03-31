from __future__ import annotations

from datetime import datetime
from enum import Enum
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TransactionType(str, Enum):
    income = "income"
    expense = "expense"


class TransactionOperationType(str, Enum):
    regular = "regular"
    transfer = "transfer"
    investment_buy = "investment_buy"
    investment_sell = "investment_sell"
    credit_disbursement = "credit_disbursement"
    credit_payment = "credit_payment"
    credit_interest = "credit_interest"
    debt = "debt"
    refund = "refund"
    adjustment = "adjustment"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    target_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    credit_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
    counterparty_id: Mapped[int | None] = mapped_column(ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB", server_default="RUB")
    type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=TransactionOperationType.regular.value,
        server_default=TransactionOperationType.regular.value,
        index=True,
    )
    credit_principal_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    credit_interest_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    debt_direction: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    affects_analytics: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)

    transfer_pair_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id", ondelete="SET NULL"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="transactions")
    account = relationship("Account", back_populates="transactions", foreign_keys=[account_id])
    target_account = relationship("Account", foreign_keys=[target_account_id])
    credit_account = relationship("Account", foreign_keys=[credit_account_id])
    category = relationship("Category", back_populates="transactions")
    counterparty = relationship("Counterparty", back_populates="transactions")
    goal = relationship("Goal", back_populates="transactions", foreign_keys=[goal_id])

    @property
    def category_priority(self) -> str | None:
        return self.category.priority if self.category else None


    @property
    def counterparty_name(self) -> str | None:
        return self.counterparty.name if self.counterparty else None
