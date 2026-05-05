from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BankSupportRequest(Base):
    __tablename__ = "bank_support_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # Nullable: user may name a bank that's not in `banks` (regional / niche).
    # `bank_name` always carries the human-readable label.
    bank_id: Mapped[int | None] = mapped_column(
        ForeignKey("banks.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'pending' | 'in_review' | 'added' | 'rejected' — enforced via CHECK
    # constraint at DB level (migration 0061).
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bank = relationship("Bank")
