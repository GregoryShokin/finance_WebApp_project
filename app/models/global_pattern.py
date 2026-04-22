from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class GlobalPattern(Base):
    """A bank-specific classification pattern confirmed by multiple independent users.

    When `user_count >= GLOBAL_PATTERN_MIN_USERS` the pattern becomes active
    and is offered as a suggestion to all users importing from the same bank.

    Privacy guarantees:
      - skeleton: already anonymised (identifiers replaced with placeholders)
      - no user PII stored here — only aggregated counts
      - category stored by name (not ID), resolved per-user at suggestion time
    """
    __tablename__ = "global_patterns"
    __table_args__ = (
        UniqueConstraint("bank_code", "skeleton", "suggested_category_name",
                         name="uq_global_pattern_bank_skeleton_cat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bank_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    skeleton: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    # category_kind: 'income' | 'expense' — derived from confirmed category
    category_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    suggested_category_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Aggregated statistics (no per-user data)
    user_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_confirms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    votes: Mapped[list["GlobalPatternVote"]] = relationship("GlobalPatternVote", back_populates="pattern", cascade="all, delete-orphan")


class GlobalPatternVote(Base):
    """Records which users have confirmed a global pattern (deduplication).

    One row per (pattern, user) — upserted on each confirmation.
    """
    __tablename__ = "global_pattern_votes"
    __table_args__ = (
        UniqueConstraint("pattern_id", "user_id", name="uq_global_vote_pattern_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    pattern_id: Mapped[int] = mapped_column(
        ForeignKey("global_patterns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vote_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    pattern: Mapped["GlobalPattern"] = relationship("GlobalPattern", back_populates="votes")
