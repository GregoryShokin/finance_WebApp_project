"""Layer 3: cross-user collective learning for import classification.

When multiple independent users confirm the same (bank_code, skeleton,
category) mapping, the system promotes it to a global pattern and offers
it as a suggestion to all new users importing from that bank.

Privacy guarantees:
  - Only anonymized skeletons (no PII) are stored globally.
  - Individual user votes are stored in `global_pattern_votes` but
    contain no PII beyond user_id (which is internal).
  - Patterns are bank-scoped — they never cross bank boundaries.

Threshold: `GLOBAL_PATTERN_MIN_USERS` unique users must confirm
the same (bank_code, skeleton, category_name) for the pattern to
become active.  Default: 3 (configurable via settings).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.global_pattern import GlobalPattern, GlobalPatternVote
from app.models.transaction_category_rule import TransactionCategoryRule

logger = logging.getLogger(__name__)

# Minimum number of distinct users who must confirm a pattern
# before it is shown to new users.
GLOBAL_PATTERN_MIN_USERS: int = 3


@dataclass(frozen=True)
class GlobalPatternMatch:
    """Result of a global pattern lookup for a cluster."""
    pattern_id: int
    suggested_category_name: str
    category_kind: str
    user_count: int
    total_confirms: int


class GlobalPatternService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Public: record a user confirmation
    # ------------------------------------------------------------------

    def on_rule_confirmed(self, rule: TransactionCategoryRule) -> None:
        """Record that a user confirmed a bank-scope rule.

        Called by RuleStrengthService after incrementing confirms on a
        bank-scope rule. Idempotent per (user, pattern) — voting twice
        only increments `vote_count`, not `user_count`.

        No-op when:
          - rule is not bank-scope
          - rule has no bank_code
          - category cannot be loaded
        """
        if rule.scope != "bank" or not rule.bank_code:
            return

        # Load category to get name and kind.
        category = (
            self.db.query(Category)
            .filter(Category.id == rule.category_id)
            .first()
        )
        if category is None:
            return

        skeleton = rule.normalized_description
        bank_code = rule.bank_code
        category_name = category.name
        category_kind = category.kind
        user_id = rule.user_id

        try:
            self._record_vote(
                bank_code=bank_code,
                skeleton=skeleton,
                category_name=category_name,
                category_kind=category_kind,
                user_id=user_id,
            )
        except Exception:  # noqa: BLE001 — never break the import pipeline
            logger.warning(
                "GlobalPatternService.on_rule_confirmed failed for rule %s",
                rule.id,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Public: query
    # ------------------------------------------------------------------

    def get_matching_pattern(
        self, *, bank_code: str, skeleton: str
    ) -> GlobalPatternMatch | None:
        """Return the best active global pattern for this bank + skeleton.

        Returns None when no active pattern exists (not enough users have
        confirmed it yet, or the bank/skeleton combination is unknown).
        """
        pattern = (
            self.db.query(GlobalPattern)
            .filter(
                GlobalPattern.bank_code == bank_code,
                GlobalPattern.skeleton == skeleton,
                GlobalPattern.is_active.is_(True),
            )
            .order_by(GlobalPattern.user_count.desc())
            .first()
        )
        if pattern is None:
            return None
        return GlobalPatternMatch(
            pattern_id=pattern.id,
            suggested_category_name=pattern.suggested_category_name,
            category_kind=pattern.category_kind,
            user_count=pattern.user_count,
            total_confirms=pattern.total_confirms,
        )

    def get_all_active_for_bank(self, *, bank_code: str) -> list[GlobalPattern]:
        return (
            self.db.query(GlobalPattern)
            .filter(GlobalPattern.bank_code == bank_code, GlobalPattern.is_active.is_(True))
            .order_by(GlobalPattern.user_count.desc())
            .all()
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _record_vote(
        self,
        *,
        bank_code: str,
        skeleton: str,
        category_name: str,
        category_kind: str,
        user_id: int,
    ) -> None:
        # Find-or-create the global pattern record.
        pattern = (
            self.db.query(GlobalPattern)
            .filter(
                GlobalPattern.bank_code == bank_code,
                GlobalPattern.skeleton == skeleton,
                GlobalPattern.suggested_category_name == category_name,
            )
            .first()
        )
        if pattern is None:
            pattern = GlobalPattern(
                bank_code=bank_code,
                skeleton=skeleton,
                category_kind=category_kind,
                suggested_category_name=category_name,
                user_count=0,
                total_confirms=0,
                is_active=False,
            )
            self.db.add(pattern)
            self.db.flush()  # assigns pattern.id

        # Upsert the vote for this user.
        vote = (
            self.db.query(GlobalPatternVote)
            .filter(
                GlobalPatternVote.pattern_id == pattern.id,
                GlobalPatternVote.user_id == user_id,
            )
            .first()
        )
        if vote is None:
            vote = GlobalPatternVote(
                pattern_id=pattern.id,
                user_id=user_id,
                vote_count=1,
            )
            self.db.add(vote)
        else:
            vote.vote_count += 1

        self.db.flush()

        # Recount distinct users.
        user_count: int = (
            self.db.query(GlobalPatternVote)
            .filter(GlobalPatternVote.pattern_id == pattern.id)
            .count()
        )
        total_confirms: int = (
            self.db.query(GlobalPatternVote)
            .filter(GlobalPatternVote.pattern_id == pattern.id)
        ).with_entities(
            GlobalPatternVote.vote_count
        ).all()
        total_confirms_int = sum(row[0] for row in total_confirms)

        pattern.user_count = user_count
        pattern.total_confirms = total_confirms_int

        # Promote to active once enough distinct users have confirmed.
        if not pattern.is_active and user_count >= GLOBAL_PATTERN_MIN_USERS:
            pattern.is_active = True
            logger.info(
                "GlobalPattern %d promoted to active: bank=%s skeleton=%r "
                "category=%r user_count=%d",
                pattern.id, bank_code, skeleton[:60], category_name, user_count,
            )

        self.db.add(pattern)
        self.db.flush()
