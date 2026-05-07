"""Brand recognition resolver (Brand registry §4 — Ph3).

Given a normalized row's skeleton + tokens, returns the best matching
Brand or None. The result drives the inline-prompt UX («Это Пятёрочка?»)
and seeds future bindings — the resolver itself is read-only.

Resolution pipeline (kind priority, first match wins):

    sbp_merchant_id  →  org_full  →  text  →  alias_exact

Within a single kind, sort by:
    1. user-scope first (private overrides global at equal kind/length)
    2. pattern length DESC (longer text substrings beat shorter ones)
    3. (confirms - rejections) DESC (better-confirmed patterns prevail)
    4. id ASC (deterministic tie-break)

Confidence per kind (multiplied by `confidence_factor` smoothing and an
optional length factor):

    sbp_merchant_id  → 0.99
    org_full         → 0.95
    text             → 0.80 × min(1.0, len(pattern)/8)
    alias_exact      → 0.85

`confidence_factor` = (confirms + 1) / (confirms + rejections + 1)
    fresh seed pattern (0/0) → 1.0; heavy rejections drag toward 0.

Below `BRAND_PROMPT_THRESHOLD` (0.65) the resolver returns None — the
moderator UI must NOT show «Это <brand>?» on a weak guess.

Patterns are loaded once per (resolver instance, user_id) and cached. The
PreviewRowProcessor calls resolve() once per row in a session; with ~50–
100 active patterns this is a handful of dict-lookups + substring tests.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.brand import Brand, BrandPattern
from app.repositories.brand_repository import BrandRepository
from app.services.import_normalizer_v2 import ExtractedTokens

logger = logging.getLogger(__name__)


KIND_PRIORITY: tuple[str, ...] = (
    "sbp_merchant_id",
    "org_full",
    "text",
    "alias_exact",
)

_KIND_BASE_CONFIDENCE: dict[str, float] = {
    "sbp_merchant_id": 0.99,
    "org_full": 0.95,
    "text": 0.80,
    "alias_exact": 0.85,
}

# Below this score the resolver stays silent — see module docstring.
BRAND_PROMPT_THRESHOLD: float = 0.65

# Normalization constant for `text`-kind length factor: a 6-char pattern is
# considered fully discriminating, anything shorter scales down linearly.
# Calibrated against the seed registry so common Russian merchant names
# clear threshold without false-positive risk:
#   "pyaterochka" (11) → 1.00 → conf 0.80 ✓
#   "magnit"      (6)  → 1.00 → conf 0.80 ✓
#   "lenta"       (5)  → 0.83 → conf 0.67 ✓ (just above 0.65)
#   "kfc"         (3)  → 0.50 → conf 0.40 ✗ (must use alias_exact instead)
#   "wb"          (2)  → 0.33 → conf 0.27 ✗ (must use alias_exact instead)
_TEXT_LENGTH_NORM: float = 6.0


@dataclass(frozen=True)
class BrandMatch:
    """Outcome of a successful brand resolution."""

    brand_id: int
    brand_slug: str
    canonical_name: str
    category_hint: str | None
    pattern_id: int
    kind: str
    confidence: float


class BrandResolverService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = BrandRepository(db)
        self._patterns_cache: dict[int, list[BrandPattern]] = {}
        self._brands_cache: dict[int, Brand] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        *,
        skeleton: str,
        tokens: ExtractedTokens,
        user_id: int,
    ) -> BrandMatch | None:
        """Best brand match for the row, or None when no signal clears the threshold."""
        patterns = self._load_patterns(user_id=user_id)
        if not patterns:
            return None

        skeleton_lc = (skeleton or "").lower()

        for kind in KIND_PRIORITY:
            kind_patterns = [p for p in patterns if p.kind == kind]
            if not kind_patterns:
                continue
            kind_patterns.sort(key=_sort_key)

            for p in kind_patterns:
                score = _score_match(
                    pattern_value=p.pattern,
                    kind=p.kind,
                    skeleton_lc=skeleton_lc,
                    tokens=tokens,
                    is_regex=bool(p.is_regex),
                )
                if score is None:
                    continue
                cf = _confidence_factor(p.confirms, p.rejections)
                final = score * cf
                if final < BRAND_PROMPT_THRESHOLD:
                    continue
                brand = self._get_brand(p.brand_id)
                if brand is None:
                    continue
                return BrandMatch(
                    brand_id=brand.id,
                    brand_slug=brand.slug,
                    canonical_name=brand.canonical_name,
                    category_hint=brand.category_hint,
                    pattern_id=p.id,
                    kind=p.kind,
                    confidence=round(final, 4),
                )
        return None

    # ------------------------------------------------------------------
    # Caching
    # ------------------------------------------------------------------

    def _load_patterns(self, *, user_id: int) -> list[BrandPattern]:
        cached = self._patterns_cache.get(user_id)
        if cached is not None:
            return cached
        patterns = self.repo.list_active_patterns_for_user(user_id=user_id)
        self._patterns_cache[user_id] = patterns
        self._prefetch_brands(p.brand_id for p in patterns)
        return patterns

    def _prefetch_brands(self, brand_ids: Iterable[int]) -> None:
        missing = [bid for bid in set(brand_ids) if bid not in self._brands_cache]
        if not missing:
            return
        rows = self.db.query(Brand).filter(Brand.id.in_(missing)).all()
        for b in rows:
            self._brands_cache[b.id] = b

    def _get_brand(self, brand_id: int) -> Brand | None:
        cached = self._brands_cache.get(brand_id)
        if cached is not None:
            return cached
        brand = self.db.query(Brand).filter(Brand.id == brand_id).first()
        if brand is not None:
            self._brands_cache[brand_id] = brand
        return brand


# ---------------------------------------------------------------------------
# Module-level helpers (testable in isolation)
# ---------------------------------------------------------------------------


def _sort_key(pattern: BrandPattern) -> tuple[int, int, float, int]:
    """Order patterns within one kind: user-scope > length DESC > strength DESC > id."""
    user_scope_first = 0 if pattern.scope_user_id is not None else 1
    length_desc = -len(pattern.pattern or "")
    strength = float((pattern.confirms or Decimal("0")) - (pattern.rejections or Decimal("0")))
    return (user_scope_first, length_desc, -strength, pattern.id)


def _confidence_factor(confirms, rejections) -> float:
    """Smoothed (confirms + 1) / (confirms + rejections + 1).

    Fresh seed patterns (0/0) start at 1.0 — they get full base confidence
    on first encounter; rejections drag it down monotonically.
    """
    c = float(confirms or 0)
    r = float(rejections or 0)
    return (c + 1.0) / (c + r + 1.0)


def _score_match(
    *,
    pattern_value: str,
    kind: str,
    skeleton_lc: str,
    tokens: ExtractedTokens,
    is_regex: bool = False,
) -> float | None:
    """Return per-kind base confidence (no error_ratio yet) on match, else None.

    `is_regex` only affects kind='text'. Maintainer-curated regex patterns
    let one BrandPattern match split-token descriptions like
    "yandex 5815 plus" via `yandex.{0,30}plus` — substring matching can't
    do that without dropping the structural anchor between the brand
    prefix and its sub-product.
    """
    if not pattern_value:
        return None

    if kind == "sbp_merchant_id":
        if not tokens.sbp_merchant_id or tokens.sbp_merchant_id != pattern_value:
            return None
        return _KIND_BASE_CONFIDENCE[kind]

    if kind == "org_full":
        if not tokens.counterparty_org:
            return None
        if _normalize_org(tokens.counterparty_org) != _normalize_org(pattern_value):
            return None
        return _KIND_BASE_CONFIDENCE[kind]

    if kind == "text":
        if not skeleton_lc:
            return None
        if is_regex:
            try:
                if re.search(pattern_value, skeleton_lc, flags=re.IGNORECASE) is None:
                    return None
            except re.error as exc:
                # Bad maintainer pattern — log once, never crash a preview.
                logger.warning(
                    "invalid brand regex pattern %r: %s", pattern_value, exc,
                )
                return None
        else:
            needle = pattern_value.lower()
            if needle not in skeleton_lc:
                return None
        length_factor = min(1.0, len(pattern_value) / _TEXT_LENGTH_NORM)
        return _KIND_BASE_CONFIDENCE[kind] * length_factor

    if kind == "alias_exact":
        if not skeleton_lc:
            return None
        if skeleton_lc.strip() != pattern_value.lower().strip():
            return None
        return _KIND_BASE_CONFIDENCE[kind]

    return None


def _normalize_org(value: str) -> str:
    """Collapse whitespace and lower-case for org_full comparison."""
    return " ".join((value or "").split()).lower()
