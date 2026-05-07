from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


BRAND_PATTERN_KINDS: frozenset[str] = frozenset({
    "text",
    "sbp_merchant_id",
    "org_full",
    "alias_exact",
})


class Brand(Base):
    """Canonical merchant identity used by the brand-recognition layer.

    Sits ABOVE existing fingerprint/skeleton counterparty bindings — the
    resolver returns a Brand, the moderator UI shows «Это <canonical_name>?»,
    and on confirm the binding flows through the existing CounterpartyFingerprint
    / CounterpartyIdentifier path. Brand never participates in DB writes
    on Transactions directly (yet).

    Scope: `is_global=True` brands are seeded by maintainers; `is_global=False`
    are private user-created (e.g. the user's local coffee shop). Promotion to
    global is a manual maintainer step.
    """

    __tablename__ = "brands"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_brands_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_global: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BrandPattern(Base):
    """One concrete way a Brand appears in raw bank-statement data.

    Resolution priority (Brand registry §3): sbp_merchant_id > org_full >
    text (longest-pattern-first) > alias_exact. Within a kind, tie-break
    by `(confirms - rejections, priority, length)` — see §4.

    Scope mirrors Brand but with one twist: a private pattern can attach to a
    GLOBAL brand. User notices that local PYAT-MICRO-3 abbreviation always
    means Пятёрочка → creates a user-scope text pattern pointing at the
    global Pyaterochka brand. Resolver tries user-scope first, so user
    overrides cleanly — without forking the global brand record.

    Strength counters are per-pattern, not per-brand: an SBP merchant_id
    pattern is rock-solid and earns confirms quickly, while a 4-letter text
    alias may collide and accumulate rejections. Auto-deactivation is a Ph6
    concern; for now `is_active` is a simple flag (default true) and the
    deactivation service comes alongside the confirm/reject API.
    """

    __tablename__ = "brand_patterns"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('text', 'sbp_merchant_id', 'org_full', 'alias_exact')",
            name="ck_brand_patterns_kind",
        ),
        CheckConstraint(
            "(is_global = true AND scope_user_id IS NULL)"
            " OR (is_global = false AND scope_user_id IS NOT NULL)",
            name="ck_brand_patterns_scope_consistency",
        ),
        Index(
            "ix_brand_patterns_resolver",
            "kind",
            "is_active",
            "is_global",
            "scope_user_id",
        ),
        Index(
            "uq_brand_patterns_brand_kind_pattern_scope",
            "brand_id",
            "kind",
            "pattern",
            "scope_user_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    pattern: Mapped[str] = mapped_column(String(256), nullable=False)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100",
    )
    is_regex: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    confirms: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0"), server_default="0",
    )
    rejections: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0"), server_default="0",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    is_global: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    scope_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
