"""CapitalSnapshot model — monthly snapshot of user capital for trend analysis.

Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §2.3
Decision 2026-04-19 (Phase 3, Block A).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CapitalSnapshot(Base):
    __tablename__ = "capital_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    liquid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    credit_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    real_assets_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    broker_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    receivable_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    counterparty_debt: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    capital: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    net_capital: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "snapshot_month", name="uq_capital_snapshots_user_month"),
    )

    user = relationship("User")
