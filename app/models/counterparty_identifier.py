from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CounterpartyIdentifier(Base):
    """User-scoped binding of a raw identifier to a Counterparty.

    Complements `CounterpartyFingerprint`. The fingerprint table keys by the
    full v2 fingerprint (bank + account_id + direction + skeleton + identifier),
    which is the right granularity for brand-style bindings ("Вкусная точка"
    appearing as several skeletons) but too narrow for identifier-carrying
    rows — a phone / contract / IBAN / card is the same person regardless of
    which account paid them, so a binding made on one bank statement should
    resolve on the next.

    Resolution order at cluster build time: identifier binding first (if the
    cluster has an `identifier_key`/`identifier_value`), then fall back to
    fingerprint binding for skeleton-only clusters.
    """
    __tablename__ = "counterparty_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "identifier_kind", "identifier_value",
            name="uq_cp_identifier_user_kind_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(128), nullable=False)
    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("counterparties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
