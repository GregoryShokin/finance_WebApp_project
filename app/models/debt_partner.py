from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DebtPartner(Base):
    """A person or business the user has a debt relationship with.

    Parallel to `Counterparty` but scoped exclusively to operation_type='debt'
    transactions. Keeping the two entities apart prevents the moderator from
    offering "Пятёрочка" as a possible debtor, and the debt form from offering
    arbitrary cluster merchants. Balances are computed on read from the
    related debt transactions (filtered by `debt_partner_id`).
    """
    __tablename__ = "debt_partners"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_debt_partner_user_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    opening_receivable_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    opening_payable_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    transactions = relationship("Transaction", back_populates="debt_partner")
