from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CounterpartyFingerprint(Base):
    """User-scoped binding of a fingerprint to a Counterparty entity.

    Phase 3 — counterparty-centric import. Every time the user picks a
    counterparty for a cluster at bulk-apply time, a binding is created for
    each unique fingerprint in that cluster. On the next import those
    fingerprints are grouped under the counterparty's umbrella in the UI
    (independent of skeleton/brand), and the cluster-level category /
    counterparty is resolved through the counterparty instead of through
    per-skeleton rules.

    Unlike FingerprintAlias (which redirects fingerprint → fingerprint),
    this table resolves fingerprint → counterparty as a first-class
    relationship. It lets a single counterparty accumulate many skeletons
    (e.g. "Вкусная точка", "Вкусная Точка", "VKUSNOITOCHKA") without
    requiring them to collapse to one fingerprint.
    """
    __tablename__ = "counterparty_fingerprints"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "fingerprint",
            name="uq_cp_fingerprint_user_fp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("counterparties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
