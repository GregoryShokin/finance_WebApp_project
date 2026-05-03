from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Boolean, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Spec §13 (v1.20). is_closed=True is the strong "this account stopped
    # existing on closed_at" state — kept in DB for history but hidden from
    # active lists. Distinct from is_active=False (temporary hide). closed_at
    # is the recorded closure date. Both are user-driven; never auto-set.
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    closed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False, default="main", server_default="main", index=True)
    is_credit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    credit_limit_original: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    credit_current_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    credit_interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    credit_term_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_payment: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    deposit_interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    deposit_open_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deposit_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    deposit_capitalization_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    statement_account_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="accounts")
    bank = relationship("Bank", back_populates="accounts")
    transactions = relationship("Transaction", back_populates="account", foreign_keys="Transaction.account_id")
