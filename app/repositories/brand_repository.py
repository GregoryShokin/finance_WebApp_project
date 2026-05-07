from __future__ import annotations

from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.brand import BRAND_PATTERN_KINDS, Brand, BrandPattern


class BrandRepository:
    """Read/write access for Brand and BrandPattern.

    Strength counters (`confirms`/`rejections`) are NOT manipulated here —
    that's a Ph6 concern alongside the confirm/reject API. This repo only
    creates patterns and reads them; the resolver service consumes
    `list_active_patterns_for_user` to answer «which brand is this row?».
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Brand ───────────────────────────────────────────────────────────

    def get_brand(self, brand_id: int) -> Brand | None:
        return self.db.query(Brand).filter(Brand.id == brand_id).first()

    def get_brand_by_slug(self, slug: str) -> Brand | None:
        return self.db.query(Brand).filter(Brand.slug == slug).first()

    def list_brands_for_user(self, *, user_id: int) -> list[Brand]:
        """Brands visible to one user — every global brand plus their private ones.

        Used by the moderator UI dropdown («выбрать другой бренд»).
        """
        return (
            self.db.query(Brand)
            .filter(
                or_(
                    Brand.is_global.is_(True),
                    Brand.created_by_user_id == user_id,
                )
            )
            .order_by(Brand.canonical_name.asc())
            .all()
        )

    def list_global_brands(self) -> list[Brand]:
        return (
            self.db.query(Brand)
            .filter(Brand.is_global.is_(True))
            .order_by(Brand.canonical_name.asc())
            .all()
        )

    def create_brand(
        self,
        *,
        slug: str,
        canonical_name: str,
        category_hint: str | None = None,
        is_global: bool = False,
        created_by_user_id: int | None = None,
    ) -> Brand:
        if is_global and created_by_user_id is not None:
            raise ValueError("global brand must not carry created_by_user_id")
        if not is_global and created_by_user_id is None:
            raise ValueError("private brand requires created_by_user_id")
        brand = Brand(
            slug=slug,
            canonical_name=canonical_name,
            category_hint=category_hint,
            is_global=is_global,
            created_by_user_id=created_by_user_id,
        )
        self.db.add(brand)
        self.db.flush()
        return brand

    # ── BrandPattern ────────────────────────────────────────────────────

    def list_active_patterns_for_user(
        self, *, user_id: int,
    ) -> list[BrandPattern]:
        """Resolver feed — every active pattern visible to one user.

        Order matters for the resolver (Brand registry §4): kind priority
        first, then pattern length DESC inside the kind so longer text
        substrings beat shorter ones. We sort here so the resolver can
        iterate without re-sorting per-row.
        """
        return (
            self.db.query(BrandPattern)
            .filter(
                BrandPattern.is_active.is_(True),
                or_(
                    BrandPattern.is_global.is_(True),
                    BrandPattern.scope_user_id == user_id,
                ),
            )
            .order_by(
                BrandPattern.priority.desc(),
                BrandPattern.id.asc(),
            )
            .all()
        )

    def get_pattern(
        self,
        *,
        brand_id: int,
        kind: str,
        pattern: str,
        scope_user_id: int | None,
    ) -> BrandPattern | None:
        return (
            self.db.query(BrandPattern)
            .filter(
                BrandPattern.brand_id == brand_id,
                BrandPattern.kind == kind,
                BrandPattern.pattern == pattern,
                BrandPattern.scope_user_id.is_(None) if scope_user_id is None
                else BrandPattern.scope_user_id == scope_user_id,
            )
            .first()
        )

    def upsert_pattern(
        self,
        *,
        brand_id: int,
        kind: str,
        pattern: str,
        is_global: bool,
        scope_user_id: int | None = None,
        priority: int = 100,
        is_regex: bool = False,
    ) -> tuple[BrandPattern, bool]:
        """Idempotent create-or-fetch by (brand_id, kind, pattern, scope_user_id).

        Used by the seed script (Ph2) so re-running it doesn't duplicate
        rows, and by the future learning loop (Ph6) when a user's manual
        brand attachment grows a private pattern.

        Strength counters are NOT touched here — they belong to confirm/reject.
        """
        if kind not in BRAND_PATTERN_KINDS:
            raise ValueError(f"unsupported BrandPattern.kind: {kind!r}")
        if is_global and scope_user_id is not None:
            raise ValueError("global pattern must not carry scope_user_id")
        if not is_global and scope_user_id is None:
            raise ValueError("private pattern requires scope_user_id")

        existing = self.get_pattern(
            brand_id=brand_id,
            kind=kind,
            pattern=pattern,
            scope_user_id=scope_user_id,
        )
        if existing is not None:
            return existing, False

        bp = BrandPattern(
            brand_id=brand_id,
            kind=kind,
            pattern=pattern,
            priority=priority,
            is_regex=is_regex,
            confirms=Decimal("0"),
            rejections=Decimal("0"),
            is_active=True,
            is_global=is_global,
            scope_user_id=scope_user_id,
        )
        self.db.add(bp)
        self.db.flush()
        return bp, True

    def list_patterns_for_brand(
        self, *, brand_id: int,
    ) -> list[BrandPattern]:
        return (
            self.db.query(BrandPattern)
            .filter(BrandPattern.brand_id == brand_id)
            .order_by(BrandPattern.id.asc())
            .all()
        )
