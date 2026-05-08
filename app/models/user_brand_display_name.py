from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserBrandDisplayName(Base):
    """Per-user override for the visible label of a Brand.

    Use case: the global Brand «Пятёрочка» exists in the registry, but
    a particular user always called their local Counterparty «Пятёрочка
    у дома». After Phase C the user's transactions roll up under the
    global brand, but they still see their preferred label in lists,
    chronological view, dashboards.

    Mirror of UserBrandCategoryOverride shape. UNIQUE(user_id, brand_id)
    enforces one display label per user-brand pair. ON DELETE CASCADE
    on both FKs, same reasoning as the category-override table — this
    is a configuration preference, not an audit log.

    Created in migration 0067 on rows where Counterparty.name case-folds
    to an existing Brand.canonical_name but the spelling differs.
    """

    __tablename__ = "user_brand_display_names"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "brand_id",
            name="uq_user_brand_display_names_user_brand",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
