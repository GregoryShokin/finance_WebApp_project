from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BrandFingerprint(Base):
    """User-scoped binding of a fingerprint to a Brand entity.

    Successor to `CounterpartyFingerprint`. Phase C of the Brand merge
    (migration 0067) stood this table up alongside the legacy one and
    backfilled rows from CP-fingerprints via the case-fold name lookup.
    During step 2/3 both tables are written in parallel; step 4 stops
    writing to counterparty_fingerprints and step 5 drops it.

    Same shape as the legacy table — `counterparty_id` simply renamed
    to `brand_id`, FK now points at `brands.id`. Brands are sometimes
    global, so the binding stays user-scoped (a global brand can
    accumulate per-user fingerprints without leaking across users).
    """
    __tablename__ = "brand_fingerprints"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "fingerprint",
            name="uq_brand_fingerprint_user_fp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
