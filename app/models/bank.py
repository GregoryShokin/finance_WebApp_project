from datetime import date

from sqlalchemy import Boolean, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class Bank(Base):
    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    bik: Mapped[str | None] = mapped_column(String(9), nullable=True, unique=True, index=True)
    is_popular: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Whitelist for import (Этап 1 MVP launch). Allowed values:
    # 'supported' | 'in_review' | 'pending' | 'broken'. Enforced via CHECK
    # constraint at DB level (migration 0060). Synced on startup from
    # SUPPORTED_BANK_CODES — manual statuses ('in_review', 'broken') are
    # preserved by ensure_extractor_status_baseline.
    extractor_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True,
    )
    extractor_last_tested_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    extractor_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    accounts = relationship("Account", back_populates="bank")
