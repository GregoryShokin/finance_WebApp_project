"""Commit orchestrator for the import pipeline (spec §5.4, §10.2, §12.1).

Owns the per-row decision tree at commit time:

  1. Filter eligible rows (skip parked/duplicate/error/untouched-warning).
  2. Re-run §12.1 transfer-integrity gate with `final=True`.
  3. Build transaction payloads.
  4. Pick the transaction-creation path:
       transfer with target  → TransferLinkingService (3 branches)
       requires_credit_split → CreditSplitService
       otherwise             → TransactionService (one or many split parts)
  5. Stamp the row as committed and link the created TX.
  6. Update §10.2 rule statistics via RuleStatsCommitter.
  7. Refund-fingerprint binding side-effect (§6.2 / §5.5 follow-up).

Extracted from `import_service.commit_import` 2026-04-29 as step 6 of the §1
backlog god-object decomposition. Owns the per-row try/except boundary; the
caller (`ImportService.commit_import`) still owns the `SELECT ... FOR UPDATE`
and final session-status / summary updates.
"""
from __future__ import annotations

import logging
from decimal import InvalidOperation
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository
from app.services.counterparty_fingerprint_service import CounterpartyFingerprintService
from app.services.credit_split_service import CreditSplitService
from app.services.import_post_processor import ImportPostProcessor
from app.services.rule_stats_committer import RuleStatsCommitter
from app.services.transaction_service import TransactionService, TransactionValidationError
from app.services.transfer_linking_service import TransferLinkingError, TransferLinkingService

logger = logging.getLogger(__name__)


# Mirrors `app.services.import_service.NON_ANALYTICS_OPERATION_TYPES`. Imported
# lazily to avoid a circular dependency between commit_orchestrator and the
# orchestrator's caller.
def _non_analytics_types() -> set[str]:
    from app.services.import_service import NON_ANALYTICS_OPERATION_TYPES
    return NON_ANALYTICS_OPERATION_TYPES


class CommitCounters:
    __slots__ = (
        "imported", "skipped", "duplicate", "error", "review", "parked",
    )

    def __init__(self) -> None:
        self.imported = 0
        self.skipped = 0
        self.duplicate = 0
        self.error = 0
        self.review = 0
        self.parked = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "imported_count": self.imported,
            "skipped_count": self.skipped,
            "duplicate_count": self.duplicate,
            "error_count": self.error,
            "review_count": self.review,
            "parked_count": self.parked,
        }


class CommitOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        import_repo: ImportRepository,
        category_rule_repo: TransactionCategoryRuleRepository,
        transaction_service: TransactionService,
        transfer_linker: TransferLinkingService,
        counterparty_fp_service: CounterpartyFingerprintService,
        prepare_payloads_fn: Callable[[dict[str, Any]], list[dict[str, Any]]],
    ) -> None:
        self.db = db
        self.import_repo = import_repo
        self.category_rule_repo = category_rule_repo
        self.transaction_service = transaction_service
        self.transfer_linker = transfer_linker
        self._counterparty_fp_service = counterparty_fp_service
        self._prepare_payloads = prepare_payloads_fn
        self._stats = RuleStatsCommitter(db, category_rule_repo=category_rule_repo)

    def commit_rows(
        self, *, user_id: int, rows: list[ImportRow],
    ) -> CommitCounters:
        counters = CommitCounters()
        for row in rows:
            self._commit_one(user_id=user_id, row=row, counters=counters)
        return counters

    # ------------------------------------------------------------------
    # Per-row decision tree
    # ------------------------------------------------------------------

    def _commit_one(
        self, *, user_id: int, row: ImportRow, counters: CommitCounters,
    ) -> None:
        row_status = str(row.status or "").strip().lower()

        if row_status == "parked":
            counters.parked += 1
            counters.skipped += 1
            return
        if row_status == "duplicate":
            counters.duplicate += 1
            counters.skipped += 1
            return
        if row_status == "error":
            counters.error += 1
            counters.skipped += 1
            return

        # §5.4 (v1.1): warning rows commit only after the user touched them.
        normalized_for_gate = row.normalized_data or {}
        bulk_acked = normalized_for_gate.get("cluster_bulk_acked_at")
        indiv_confirmed = normalized_for_gate.get("user_confirmed_at")
        if row_status == "warning":
            counters.review += 1
            if not (bulk_acked or indiv_confirmed):
                counters.skipped += 1
                return

        if row_status not in {"ready", "warning"}:
            counters.skipped += 1
            return

        normalized = row.normalized_data or {}

        # §12.1 commit-time guard: a transfer without both accounts is forbidden.
        gate_status, gate_issues = ImportPostProcessor.gate_transfer_integrity(
            normalized=normalized,
            current_status=row_status,
            issues=list(row.errors or []),
            final=True,
        )
        if gate_status != row_status:
            row.status = gate_status
            row.errors = gate_issues
            self.import_repo.update_row(
                row,
                status=row.status,
                errors=row.errors,
                review_required=row.status in {"warning", "error"},
            )
            if gate_status == "error":
                counters.error += 1
                counters.skipped += 1
                return
            row_status = gate_status

        try:
            payloads = self._prepare_payloads(normalized)
        except (ValueError, TypeError, InvalidOperation) as exc:
            self._mark_error(row, str(exc))
            counters.skipped += 1
            counters.error += 1
            return

        if not payloads:
            self._mark_error(row, "Строка не содержит корректных данных для создания транзакции.")
            counters.skipped += 1
            counters.error += 1
            return

        try:
            last_tx, created_count = self._dispatch_create(
                user_id=user_id, normalized=normalized, payloads=payloads,
            )
            counters.imported += created_count

            self.import_repo.update_row(
                row,
                status="committed",
                created_transaction_id=last_tx.id if last_tx is not None else None,
                review_required=False,
            )

            self._maybe_bind_refund_counterparty(user_id=user_id, row=row, normalized=normalized)
            self._stats.update_for_committed_row(
                user_id=user_id,
                normalized=normalized,
                row_status=row_status,
                bulk_acked=bulk_acked,
                individually_confirmed=indiv_confirmed,
                non_analytics_operation_types=_non_analytics_types(),
            )
        except (TransactionValidationError, TransferLinkingError) as exc:
            self._mark_error(row, str(exc))
            counters.skipped += 1
            counters.error += 1

    # ------------------------------------------------------------------
    # Path selection
    # ------------------------------------------------------------------

    def _dispatch_create(
        self,
        *,
        user_id: int,
        normalized: dict[str, Any],
        payloads: list[dict[str, Any]],
    ) -> tuple[Any, int]:
        """Returns (last_transaction, created_transactions_count)."""
        operation_type = str(normalized.get("operation_type") or "regular")
        target_account_id = normalized.get("target_account_id")

        # Path A: row-level transfer with both accounts → linker (3 branches).
        is_transfer_row = (
            operation_type == "transfer"
            and not normalized.get("requires_credit_split")
            and target_account_id not in (None, "", 0)
        )
        if is_transfer_row:
            tx = self._dispatch_transfer(
                user_id=user_id, normalized=normalized, payload=payloads[0],
            )
            return tx, 1

        # Path B: credit-payment split.
        if normalized.get("requires_credit_split"):
            split = CreditSplitService(self.db).commit_split(
                user_id=user_id, base_payload=payloads[0],
            )
            return split.last_transaction, split.transactions_created

        # Path C: regular row OR multi-part split. Each part may itself be
        # a transfer (split-part transfer) — pair-create instead of single TX.
        last_tx: Any = None
        created = 0
        for payload in payloads:
            part_op = str(payload.get("operation_type") or "regular").lower()
            if part_op == "transfer" and payload.get("target_account_id") not in (None, "", 0):
                expense_tx, _ = self.transfer_linker.create_transfer_pair(
                    user_id=user_id, payload=payload,
                )
                last_tx = expense_tx
            else:
                last_tx = self.transaction_service.create_transaction(
                    user_id=user_id, payload=payload,
                )
            created += 1
        return last_tx, created

    def _dispatch_transfer(
        self, *, user_id: int, normalized: dict[str, Any], payload: dict[str, Any],
    ) -> Any:
        """Pick the right transfer-creation branch (§10.6, §10.7, §12.9).

        Three branches in order:
          A) cross-session pair: partner row already committed → link to phantom.
          B) committed-orphan link: matched_tx_id present → link to it.
          C) fall-through: brand-new pair via create_transfer_pair.
        """
        transfer_match_meta = normalized.get("transfer_match") or {}
        matched_tx_id = transfer_match_meta.get("matched_tx_id")
        matched_row_id = transfer_match_meta.get("matched_row_id")

        linked_tx = None
        if matched_row_id and not matched_tx_id:
            linked_tx = self.transfer_linker.link_to_committed_cross_session_phantom(
                user_id=user_id,
                payload=payload,
                matched_import_row_id=int(matched_row_id),
            )
        if linked_tx is None and matched_tx_id:
            linked_tx = self.transfer_linker.link_to_committed_orphan(
                user_id=user_id,
                payload=payload,
                committed_tx_id=int(matched_tx_id),
            )
        if linked_tx is not None:
            return linked_tx

        expense_tx, income_tx = self.transfer_linker.create_transfer_pair(
            user_id=user_id, payload=payload,
        )
        # Link the import row to the TX on its own account side.
        tx_type = str((payload.get("type") or "expense")).lower()
        return income_tx if tx_type == "income" else expense_tx

    # ------------------------------------------------------------------
    # Side effects + helpers
    # ------------------------------------------------------------------

    def _mark_error(self, row: ImportRow, message: str) -> None:
        row.status = "error"
        row.errors = list(dict.fromkeys([*(row.errors or []), message]))
        self.import_repo.update_row(
            row, status=row.status, errors=row.errors, review_required=True,
        )

    def _maybe_bind_refund_counterparty(
        self, *, user_id: int, row: ImportRow, normalized: dict[str, Any],
    ) -> None:
        """For refund rows whose preview resolved a counterparty via brand
        history, persist the fingerprint→counterparty binding so the next
        refund of the same merchant resolves directly without brand search.
        """
        if str(normalized.get("operation_type") or "") != "refund":
            return
        cp_id = normalized.get("counterparty_id")
        fp = normalized.get("fingerprint")
        if cp_id in (None, "", 0) or not fp:
            return
        try:
            self._counterparty_fp_service.bind(
                user_id=user_id,
                fingerprint=str(fp),
                counterparty_id=int(cp_id),
            )
        except Exception as exc:  # noqa: BLE001 — never block commit
            logger.warning(
                "refund counterparty binding failed row=%s: %s", row.id, exc,
            )
