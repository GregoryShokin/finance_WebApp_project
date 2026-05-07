"""Strength transitions for BrandPattern (Brand registry Ph6).

Mirrors RuleStrengthService — the only place that mutates `confirms`,
`rejections`, `is_active` on a BrandPattern. Callers (BrandConfirmService,
future learning loop) hand in pattern_id + intent; this service decides
what state changes follow.

Deactivation policy (matches §11.1 «swallow» strategy of the spec —
inactive patterns stay in the table for history, never participate in
matching). Once deactivated, a pattern does NOT auto-reactivate via
later confirms — manual maintainer toggle only. Same intent as
RuleStrengthService.

Thresholds are hardcoded for now (no live tuning need); migrate to
settings.py when Ph7+ surfaces a knob requirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.models.brand import BrandPattern


# Absolute rejection count that flips an active pattern to inactive.
DEACTIVATE_REJECTIONS: Decimal = Decimal("5")

# Error-ratio cap (rejections / (confirms + rejections)). Crossing this
# while confirms exist still deactivates — protects against heavy-traffic
# patterns where 5 absolute rejections look small next to 50 confirms.
ERROR_RATIO_CAP: float = 0.5

# Minimum total votes (confirms + rejections) before the ratio check is
# allowed to deactivate. Without this, a fresh seed pattern (0/0) gets
# nuked by a single rejection (1/1 = 100% bad). Aligned with the absolute
# threshold so neither check fires on small-sample noise.
MIN_VOTES_FOR_RATIO_DEACTIVATION: int = 5

# Default per-event deltas. Kept as constants so callers can pass weighted
# deltas later (e.g. a bulk-confirm propagating across N rows).
CONFIRM_DELTA: Decimal = Decimal("1.0")
REJECTION_DELTA: Decimal = Decimal("1.0")


class BrandPatternNotFound(LookupError):
    """Raised when a pattern_id passed to on_confirmed/on_rejected does not exist."""


@dataclass(frozen=True)
class BrandPatternTransition:
    pattern_id: int
    confirms_before: Decimal
    confirms_after: Decimal
    rejections_before: Decimal
    rejections_after: Decimal
    is_active_before: bool
    is_active_after: bool
    event: Literal["confirmed", "rejected"]

    @property
    def deactivated(self) -> bool:
        return self.is_active_before and not self.is_active_after


class BrandPatternStrengthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def on_confirmed(
        self,
        pattern_id: int,
        delta: Decimal | float | int = CONFIRM_DELTA,
    ) -> BrandPatternTransition:
        """User confirmed the brand suggested by this pattern.

        Symmetric to RuleStrengthService.on_confirmed: confirms increase,
        but a pattern that was previously deactivated (rejections piled up
        past the threshold) is NOT auto-reactivated. Maintainer must
        un-toggle is_active explicitly.
        """
        d = Decimal(str(delta))
        if d <= 0:
            raise ValueError(f"confirms delta must be > 0, got {delta}")
        pattern = self._load(pattern_id)
        before = _snapshot(pattern)
        pattern.confirms = (pattern.confirms or Decimal("0")) + d
        self.db.add(pattern)
        self.db.flush()
        return _transition(pattern, before, event="confirmed")

    def on_rejected(self, pattern_id: int) -> BrandPatternTransition:
        """User said «not this brand» — strike against the pattern.

        Active → Inactive when EITHER absolute count crosses
        DEACTIVATE_REJECTIONS OR error-ratio crosses ERROR_RATIO_CAP.
        """
        pattern = self._load(pattern_id)
        before = _snapshot(pattern)
        pattern.rejections = (pattern.rejections or Decimal("0")) + REJECTION_DELTA
        if pattern.is_active:
            total = float(pattern.confirms or 0) + float(pattern.rejections or 0)
            hit_absolute = pattern.rejections >= DEACTIVATE_REJECTIONS
            hit_ratio = (
                total >= MIN_VOTES_FOR_RATIO_DEACTIVATION
                and _error_ratio(pattern.confirms, pattern.rejections) > ERROR_RATIO_CAP
            )
            if hit_absolute or hit_ratio:
                pattern.is_active = False
        self.db.add(pattern)
        self.db.flush()
        return _transition(pattern, before, event="rejected")

    def _load(self, pattern_id: int) -> BrandPattern:
        pattern = (
            self.db.query(BrandPattern)
            .filter(BrandPattern.id == pattern_id)
            .first()
        )
        if pattern is None:
            raise BrandPatternNotFound(f"brand_pattern {pattern_id} not found")
        return pattern


@dataclass(frozen=True)
class _Before:
    confirms_before: Decimal
    rejections_before: Decimal
    is_active_before: bool


def _snapshot(pattern: BrandPattern) -> _Before:
    return _Before(
        confirms_before=pattern.confirms or Decimal("0"),
        rejections_before=pattern.rejections or Decimal("0"),
        is_active_before=pattern.is_active,
    )


def _transition(
    pattern: BrandPattern,
    before: _Before,
    *,
    event: Literal["confirmed", "rejected"],
) -> BrandPatternTransition:
    return BrandPatternTransition(
        pattern_id=pattern.id,
        confirms_before=before.confirms_before,
        confirms_after=pattern.confirms,
        rejections_before=before.rejections_before,
        rejections_after=pattern.rejections,
        is_active_before=before.is_active_before,
        is_active_after=pattern.is_active,
        event=event,
    )


def _error_ratio(confirms, rejections) -> float:
    c = float(confirms or 0)
    r = float(rejections or 0)
    total = c + r
    return r / total if total > 0 else 0.0
