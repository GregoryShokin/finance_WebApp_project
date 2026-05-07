from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserBrandCategoryOverride(Base):
    """Per-user override of a Brand's default category hint.

    Resolution order at confirm/preview time:
      1. User override for (user_id, brand_id) → its category_id.
      2. Fallback to global `Brand.category_hint` (resolved by name).

    Non-destructive — overrides are upserted, deleted explicitly, never
    silently rewritten by seed updates.
    """

    __tablename__ = "user_brand_category_overrides"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "brand_id",
            name="uq_user_brand_category_overrides_user_brand",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(), onupdate=func.now(), nullable=False,
    )
