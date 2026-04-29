"""Rule statistics committer (spec §10.2 cases A/B/C/D).

For every committed import row carrying a category, this module updates the
`TransactionCategoryRule` strength counters:

  Case A — ready row (or warning + individual confirm) AND final category
           matches the predicted one → `R.confirms += 1.0`
  Case B — warning row + cluster_bulk_acked_at AND final == predicted →
           `R.confirms += 0.5` (already applied at bulk_apply time, NOT re-counted here)
  Case C — applied_rule_id is set AND final ≠ predicted → reject old rule,
           upsert R' with the user's chosen category at the appropriate weight
  Case D — no prior rule, user explicitly chose category → upsert R' at weight

Extracted from `import_service.commit_import` 2026-04-29 as step 4 of the §1
backlog god-object decomposition. Pure delegation: no DB ownership, no
transaction boundary — caller controls commit/rollback.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository
from app.services.rule_strength_service import (
    CONFIRM_WEIGHT_READY,
    CONFIRM_WEIGHT_WARNING,
    RuleNotFound,
    RuleStrengthService,
)

logger = logging.getLogger(__name__)


class RuleStatsCommitter:
    def __init__(
        self,
        db: Session,
        *,
        category_rule_repo: TransactionCategoryRuleRepository,
    ) -> None:
        self.db = db
        self.category_rule_repo = category_rule_repo

    def update_for_committed_row(
        self,
        *,
        user_id: int,
        normalized: dict[str, Any],
        row_status: str,
        bulk_acked: Any,
        individually_confirmed: Any,
        non_analytics_operation_types: set[str],
    ) -> None:
        """Apply §10.2 case A/B/C/D logic to one row's strength counters.

        No-ops when the row has no category, has no normalized description,
        or its operation_type is in `non_analytics_operation_types`
        (transfers / credit_disbursement / refund — none of these participate
        in category-rule learning).
        """
        category_id = normalized.get("category_id")
        norm_desc = normalized.get("normalized_description")
        orig_desc = (
            normalized.get("import_original_description")
            or normalized.get("description")
        )
        operation_type = normalized.get("operation_type") or "regular"
        if not (category_id and norm_desc) or operation_type in non_analytics_operation_types:
            return

        applied_rule_id = normalized.get("applied_rule_id")
        applied_rule_cat = normalized.get("applied_rule_category_id")

        # Weight selection per spec §6.4 / §5.4:
        #   ready                                      → +1.0  (Case A)
        #   warning + user_confirmed_at  (individual)  → +1.0  (Case A — "full touch")
        #   warning + cluster_bulk_acked_at (bulk)     → +0.5  (Case B; already applied)
        already_counted_at_bulk_ack = bool(bulk_acked) and not individually_confirmed
        confirm_weight = (
            CONFIRM_WEIGHT_WARNING
            if (row_status == "warning" and bulk_acked and not individually_confirmed)
            else CONFIRM_WEIGHT_READY
        )

        from app.core.config import settings  # local import keeps test-time mocking simple
        rule_svc = RuleStrengthService(self.db, settings)
        final_cat = int(category_id)

        if (
            applied_rule_id is not None
            and applied_rule_cat is not None
            and int(applied_rule_cat) == final_cat
        ):
            # Case A/B — final == predicted.
            if already_counted_at_bulk_ack:
                # Bulk-apply already added 0.5 per row at cluster ack time.
                # Re-counting here would double the strength signal.
                return
            try:
                rule_svc.on_confirmed(applied_rule_id, confirms_delta=confirm_weight)
            except RuleNotFound:
                # Rule deleted between preview and commit — fall through to
                # case D (treat as a fresh user-driven assignment).
                self.category_rule_repo.upsert(
                    user_id=user_id,
                    normalized_description=norm_desc,
                    category_id=final_cat,
                    original_description=orig_desc or None,
                )
            return

        if applied_rule_id is not None:
            # Case C — rule applied but user changed the category.
            # Old rule gets a rejection; new R' starts at the committed weight.
            try:
                rule_svc.on_rejected(applied_rule_id)
            except RuleNotFound:
                pass  # nothing to reject — old rule gone

        # Case C upsert + Case D upsert share the same body.
        new_rule = self.category_rule_repo.upsert(
            user_id=user_id,
            normalized_description=norm_desc,
            category_id=final_cat,
            original_description=orig_desc or None,
        )
        # `upsert` creates new rules with confirms=1.0 by default. Warning-row
        # commits should land at 0.5 instead — adjust if so.
        if new_rule is not None and confirm_weight != CONFIRM_WEIGHT_READY:
            try:
                new_rule.confirms = confirm_weight
                self.db.add(new_rule)
                self.db.flush()
            except Exception as exc:  # noqa: BLE001 — never block commit on stats
                logger.warning(
                    "could not adjust new rule confirm weight: %s", exc,
                )
