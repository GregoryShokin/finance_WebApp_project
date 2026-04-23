from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FingerprintAlias(Base):
    """User-scoped redirect from one fingerprint to another.

    Created when a user explicitly attaches a row from «Требуют внимания» to an
    existing cluster — a signal that the source fingerprint is semantically the
    same merchant/counterparty as the target, even though the skeleton differs.

    On subsequent imports `FingerprintAliasService.resolve(user_id, fp)` rewrites
    the fingerprint at normalization time, so future rows with the source
    pattern land directly in the target cluster (skipping «Требуют внимания»).

    Alias chains are flattened at creation time: if `B → C` is created while
    `A → B` already exists, both aliases are rewritten to point at `C` directly.
    The resolver still caps traversal depth as a safety net.
    """
    __tablename__ = "fingerprint_aliases"
    __table_args__ = (
        UniqueConstraint("user_id", "source_fingerprint", name="uq_fp_alias_user_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
