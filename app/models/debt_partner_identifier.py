from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DebtPartnerIdentifier(Base):
    """Mirror of `BrandIdentifier` for personal contacts (DebtPartner).

    Created in migration 0069 alongside the «+ Имя / Бренд» unified bind
    flow. Once the user names a personal contact (e.g. «Брат») on a row
    that carries a phone / contract / person_name token, that token is
    persisted here so future imports of the same identifier — even on a
    different statement / account — auto-resolve to the same contact.

    Cross-account semantics: a phone number is the same person no matter
    which of the user's cards paid them, so the binding is `user_id`-
    scoped, not account-scoped.

    `identifier_kind` is one of `{phone, contract, person_hash}`. card and
    iban are intentionally NOT supported: card identifiers are reserved
    for transfer-rail bindings (spec §12.11), and IBAN / bank-account
    numbers belong to the user's own accounts, not their personal
    contacts.
    """
    __tablename__ = "debt_partner_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "identifier_kind", "identifier_value",
            name="uq_debt_partner_identifier_user_kind_value",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    identifier_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(128), nullable=False)
    debt_partner_id: Mapped[int] = mapped_column(
        ForeignKey("debt_partners.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
