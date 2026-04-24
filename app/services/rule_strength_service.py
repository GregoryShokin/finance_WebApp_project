"""Strength transitions for TransactionCategoryRule (Phase 2.3 of И-08).

This is the ONLY place that mutates `confirms`, `rejections`, `is_active`,
or `scope`. Upstream callers (ImportService.commit_*, TransactionService
edit-within-7-days) invoke `on_confirmed` or `on_rejected` and receive a
`RuleTransition` describing what changed. They never touch the counters
directly.

What happens here:
  - `confirms` / `rejections` counters increment.
  - `is_active = False → True` only on the first time `confirms` reaches
    `RULE_ACTIVATE_CONFIRMS`, AND only if `rejections == 0`. A rule that
    was previously deactivated via rejections stays inactive under
    confirm — re-enabling requires an explicit manual toggle (Phase 5).
  - `scope = exact → bank` when `confirms ≥ RULE_GENERALIZE_CONFIRMS`,
    error ratio under cap, and `bank_code` is set.
  - `is_active = True → False` when rejections cross the absolute
    threshold OR when the error ratio exceeds the cap.

What does NOT happen here:
  - Writes to any audit table (if needed, caller logs the returned
    `RuleTransition`).
  - Reset of rejections on manual re-activation — history is preserved
    until the rule is edited explicitly.
  - `legacy_pattern → bank` transition — that requires bank context from
    the moderator (Phase 4), not available at strength-update time.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.transaction_category_rule import TransactionCategoryRule

# §10.2 — confirm weights by the committing row's status.
CONFIRM_WEIGHT_READY = Decimal("1.00")     # ready row, final == predicted
CONFIRM_WEIGHT_WARNING = Decimal("0.50")   # warning row committed via bulk-ack


@dataclass(frozen=True)
class RuleTransition:
    """Snapshot of what changed during a single on_confirmed / on_rejected call."""

    rule_id: int
    confirms_before: Decimal
    confirms_after: Decimal
    rejections_before: Decimal
    rejections_after: Decimal
    is_active_before: bool
    is_active_after: bool
    scope_before: str
    scope_after: str
    event: Literal["confirmed", "rejected"]

    @property
    def activated(self) -> bool:
        return not self.is_active_before and self.is_active_after

    @property
    def deactivated(self) -> bool:
        return self.is_active_before and not self.is_active_after

    @property
    def generalized(self) -> bool:
        return self.scope_before != self.scope_after


class RuleNotFound(LookupError):
    """Raised when a rule_id passed to on_confirmed / on_rejected does not exist."""


class RuleStrengthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_confirmed(
        self, rule_id: int, confirms_delta: Decimal | float | int = CONFIRM_WEIGHT_READY,
    ) -> RuleTransition:
        """Rule was applied and the user left the result unchanged.

        §10.2: `confirms_delta` carries the committing row's weight.
          - `ready` commit (final == predicted): weight 1.0 (default).
          - `warning` commit via bulk-ack: weight 0.5 — less evidence than
            an explicit review, but still a signal worth learning from.
          - Bulk-confirm endpoint may pass N × weight in a single call.

        The ``is_active: False → True`` transition fires the first time
        ``confirms`` crosses ``RULE_ACTIVATE_CONFIRMS`` AND only if
        ``rejections == 0``. A rule previously deactivated via rejections
        cannot be silently reactivated — manual re-enable only (Phase 5).
        """
        delta = Decimal(str(confirms_delta))
        if delta <= 0:
            raise ValueError(f"confirms_delta must be > 0, got {confirms_delta}")
        rule = self._load(rule_id)
        before = _snapshot(rule)

        rule.confirms = (rule.confirms or Decimal("0")) + delta

        if (
            not rule.is_active
            and rule.rejections == 0
            and rule.confirms >= self.settings.RULE_ACTIVATE_CONFIRMS
            and before.is_active_before is False
            # Extra guard: only activate if the rule has never been deactivated
            # via rejections. At `rejections == 0` this is inherently true;
            # the explicit check keeps the intent readable.
        ):
            rule.is_active = True

        # Generalization: exact → bank on enough confirms, tolerable error
        # ratio, and a known bank. legacy_pattern stays put in 2.3 — its
        # promotion path runs through the moderator (Phase 4).
        if (
            rule.scope == "exact"
            and rule.confirms >= self.settings.RULE_GENERALIZE_CONFIRMS
            and _error_ratio(rule.confirms, rule.rejections)
            <= self.settings.RULE_ERROR_RATIO_CAP
            and rule.bank_code
        ):
            rule.scope = "bank"

        self.session.add(rule)
        self.session.flush()

        # Layer 3: feed confirmed bank-scope rules into the global pattern learner.
        if rule.scope == "bank" and rule.is_active:
            from app.services.global_pattern_service import GlobalPatternService
            GlobalPatternService(self.session).on_rule_confirmed(rule)

        return _transition(rule, before, event="confirmed")

    def on_rejected(self, rule_id: int) -> RuleTransition:
        """User overrode what the rule suggested — treat as a strike against it.

        `rejections` always increments. Deactivation fires when rejections
        cross the absolute threshold OR the error ratio exceeds the cap.
        Deactivation is reversible through manual UI toggle; this service
        never reactivates automatically.
        """
        rule = self._load(rule_id)
        before = _snapshot(rule)

        rule.rejections = (rule.rejections or Decimal("0")) + Decimal("1")

        if rule.is_active:
            hit_absolute = rule.rejections >= self.settings.RULE_DEACTIVATE_REJECTIONS
            hit_ratio = (
                _error_ratio(rule.confirms, rule.rejections)
                > self.settings.RULE_ERROR_RATIO_CAP
            )
            if hit_absolute or hit_ratio:
                rule.is_active = False

        self.session.add(rule)
        self.session.flush()
        return _transition(rule, before, event="rejected")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self, rule_id: int) -> TransactionCategoryRule:
        rule = (
            self.session.query(TransactionCategoryRule)
            .filter(TransactionCategoryRule.id == rule_id)
            .first()
        )
        if rule is None:
            raise RuleNotFound(f"rule {rule_id} not found")
        return rule


# ---------------------------------------------------------------------------
# Helpers (module-level so tests can exercise them without a service instance)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Before:
    confirms_before: Decimal
    rejections_before: Decimal
    is_active_before: bool
    scope_before: str


def _snapshot(rule: TransactionCategoryRule) -> _Before:
    return _Before(
        confirms_before=rule.confirms or Decimal("0"),
        rejections_before=rule.rejections or Decimal("0"),
        is_active_before=rule.is_active,
        scope_before=rule.scope,
    )


def _transition(
    rule: TransactionCategoryRule,
    before: _Before,
    *,
    event: Literal["confirmed", "rejected"],
) -> RuleTransition:
    return RuleTransition(
        rule_id=rule.id,
        confirms_before=before.confirms_before,
        confirms_after=rule.confirms,
        rejections_before=before.rejections_before,
        rejections_after=rule.rejections,
        is_active_before=before.is_active_before,
        is_active_after=rule.is_active,
        scope_before=before.scope_before,
        scope_after=rule.scope,
        event=event,
    )


def _error_ratio(confirms: Decimal | int, rejections: Decimal | int) -> float:
    c = float(confirms or 0)
    r = float(rejections or 0)
    total = c + r
    if total == 0:
        return 0.0
    return r / total
