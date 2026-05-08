from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BrandIdentifier(Base):
    """User-scoped binding of a raw identifier (phone / contract / IBAN /
    card) to a Brand. Successor to `CounterpartyIdentifier`.

    Created in migration 0067 alongside the legacy table. Cross-account
    semantics are unchanged: a phone number is the same person regardless
    of which of the user's accounts paid them, so a binding made on one
    bank statement should resolve on the next. With Brand replacing
    Counterparty as the merchant entity, the FK simply re-points.
    """
    __tablename__ = "brand_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "identifier_kind", "identifier_value",
            name="uq_brand_identifier_user_kind_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(128), nullable=False)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
