"""Post-processors for the import preview pipeline.

Three deterministic, idempotent passes that run after normalization and
enrichment but before the rows are written to disk:

1. `gate_transfer_integrity` — §12.1 / §5.2 trigger 6 — escalate transfers
   with only one known account to `warning` (preview) or `error` (commit/edit).
2. `apply_refund_matches` — pair expense+income within the session via
   `RefundMatcherService` (§5.5) and stamp metadata on both sides.
3. `apply_refund_cluster_overrides` — for every refund cluster, push
   counterparty + dominant-category from purchase history onto member rows
   (compensator model).

Extracted from `import_service.py` 2026-04-29 as step 5 of the §1 backlog
god-object decomposition. No DB ownership: caller controls commit/rollback.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.import_repository import ImportRepository
from app.services.refund_matcher_service import RefundMatcherService


class ImportPostProcessor:
    def __init__(self, db: Session, *, import_repo: ImportRepository) -> None:
        self.db = db
        self.import_repo = import_repo

    # ------------------------------------------------------------------
    # 1. Transfer integrity gate (§12.1, §5.2 trigger 6)
    # ------------------------------------------------------------------

    @staticmethod
    def gate_transfer_integrity(
        *,
        normalized: dict[str, Any],
        current_status: str,
        issues: list[str],
        final: bool = False,
    ) -> tuple[str, list[str]]:
        """Pure function — returns the (status, issues) tuple to apply.

        Two-stage:
          * `final=False` (preview, before async transfer-matcher runs):
            escalate to `warning`. The cross-session matcher only sees rows
            in ready/warning, so we MUST stay out of `error` long enough for
            it to attempt pairing.
          * `final=True` (post-matcher cleanup, individual edits, commit
            guard): escalate to `error`. After the matcher's last attempt,
            a still-orphan transfer is a real §12.1 violation.

        Never silently demotes `operation_type` to `regular`.
        """
        if str(normalized.get("operation_type") or "") != "transfer":
            return current_status, issues

        account_id = normalized.get("account_id")
        target_account_id = normalized.get("target_account_id")
        source_missing = account_id in (None, "", 0)
        target_missing = target_account_id in (None, "", 0)
        # §12.1 (extended): a transfer must move money BETWEEN accounts. If
        # source and target resolve to the same account, the transfer is
        # semantically invalid — at commit it would create a balance-neutral
        # phantom pair against the same account. Treat self-loop as a
        # missing target — the user must pick a real counter-account.
        self_loop = (
            not source_missing
            and not target_missing
            and account_id == target_account_id
        )
        if not (source_missing or target_missing or self_loop):
            return current_status, issues

        tx_type = str(normalized.get("type") or "expense")
        if self_loop:
            msg = "Перевод указан на тот же счёт, что и источник — укажи реальный счёт-получатель."
        elif source_missing and target_missing:
            msg = "Перевод определён, но оба счёта не распознаны — укажи их вручную."
        elif source_missing:
            msg = "Перевод определён, но счёт из выписки не распознан — укажи вручную."
        else:
            msg = (
                "Перевод определён, но счёт отправителя не распознан."
                if tx_type == "income"
                else "Перевод определён, но счёт получателя не распознан."
            )
        next_issues = list(issues)
        if msg not in next_issues:
            next_issues.append(msg)

        # §5.2 / §8.3 — terminal states stick. `duplicate` is terminal-ish;
        # `error` only deepens (never softens to warning).
        if current_status in ("duplicate", "error"):
            return current_status, next_issues

        target_status = "error" if final else "warning"
        # Status priority: ready < warning < error. Don't downgrade.
        priority = {"ready": 0, "skipped": 0, "warning": 1, "error": 2}
        if priority.get(target_status, 0) <= priority.get(current_status, 0):
            return current_status, next_issues
        return target_status, next_issues

    # ------------------------------------------------------------------
    # 2. Refund matches (§5.5) — pair expense ↔ income inside the session
    # ------------------------------------------------------------------

    def apply_refund_matches(self, *, session_id: int) -> None:
        """Run RefundMatcherService over the session's rows and persist pairs.

        For each matched pair, both sides get `normalized_data["refund_match"]`
        with: partner_row_id, partner_date, partner_description, amount,
        confidence, reasons. Status / operation_type remain user-owned.
        Rows already classified as transfer are excluded — refund and transfer
        are mutually exclusive labels for the same row.
        """
        rows = self.import_repo.get_rows(session_id=session_id)
        candidates: list[dict[str, Any]] = []
        row_by_id: dict[int, ImportRow] = {}
        for row in rows:
            nd = dict(row.normalized_data_json or {})
            if str(nd.get("operation_type") or "") == "transfer":
                continue
            if str(row.status or "").lower() in ("duplicate", "skipped", "parked", "committed", "error"):
                continue
            candidates.append({
                "row_id": row.id,
                "amount": nd.get("amount"),
                "direction": nd.get("direction") or nd.get("type"),
                "transaction_date": nd.get("transaction_date") or nd.get("date"),
                "description": nd.get("description") or "",
                "skeleton": nd.get("skeleton") or "",
                "tokens": nd.get("tokens") or {},
            })
            row_by_id[row.id] = row

        if not candidates:
            return

        matches = RefundMatcherService().match(candidates)
        if not matches:
            return

        for match in matches:
            exp_row = row_by_id.get(match.expense_row_id)
            inc_row = row_by_id.get(match.income_row_id)
            if exp_row is None or inc_row is None:
                continue
            exp_nd = dict(exp_row.normalized_data_json or {})
            inc_nd = dict(inc_row.normalized_data_json or {})
            exp_nd["refund_match"] = {
                "partner_row_id": inc_row.id,
                "partner_date": inc_nd.get("transaction_date") or inc_nd.get("date"),
                "partner_description": inc_nd.get("description") or "",
                "amount": str(match.amount),
                "confidence": match.confidence,
                "reasons": list(match.reasons),
                "side": "expense",
            }
            inc_nd["refund_match"] = {
                "partner_row_id": exp_row.id,
                "partner_date": exp_nd.get("transaction_date") or exp_nd.get("date"),
                "partner_description": exp_nd.get("description") or "",
                "amount": str(match.amount),
                "confidence": match.confidence,
                "reasons": list(match.reasons),
                "side": "income",
            }
            self.import_repo.update_row(exp_row, normalized_data=exp_nd)
            self.import_repo.update_row(inc_row, normalized_data=inc_nd)

    # ------------------------------------------------------------------
    # 3. Refund cluster overrides — counterparty + category inheritance
    # ------------------------------------------------------------------

    def apply_refund_cluster_overrides(self, *, session: ImportSession) -> None:
        """Stamp refund metadata onto every row of a refund cluster.

        For each cluster where `is_refund=True` AND a counterparty/category
        could be inherited from the user's purchase history at the same
        brand, update every row in the cluster:

          - `operation_type='refund'`
          - `type='income'` / `direction='income'`
          - `category_id` = dominant category used for past purchases at
            this counterparty (compensator model)
          - `counterparty_id` = the purchase-side counterparty

        Rows with `user_label` or a non-empty manual `counterparty_id` are
        preserved — manual overrides win over auto-inheritance.

        Refund clusters with no inheritable category still get
        `operation_type='refund'` + `type='income'` but no category — the
        row stays in attention so the user picks one manually.
        """
        # Local import — clusterer pulls in heavy SQL machinery; loading it
        # at module top would cost every importer of `import_post_processor`.
        from app.services.import_cluster_service import ImportClusterService

        cluster_svc = ImportClusterService(self.db)
        clusters = cluster_svc.build_clusters(session)
        refund_clusters = [c for c in clusters if c.is_refund]
        if not refund_clusters:
            return

        rows_by_id: dict[int, ImportRow] = {
            r.id: r for r in self.import_repo.get_rows(session_id=session.id)
        }

        for cluster in refund_clusters:
            for row_id in cluster.row_ids:
                row = rows_by_id.get(row_id)
                if row is None:
                    continue
                nd = dict(row.normalized_data_json or {})
                has_user_label = bool(nd.get("user_label"))
                nd["operation_type"] = "refund"
                nd["type"] = "income"
                nd["direction"] = "income"
                if cluster.candidate_category_id is not None and not has_user_label:
                    nd["category_id"] = int(cluster.candidate_category_id)
                if cluster.refund_resolved_counterparty_id is not None:
                    existing_cp = nd.get("counterparty_id")
                    if existing_cp in (None, "", 0):
                        nd["counterparty_id"] = int(cluster.refund_resolved_counterparty_id)
                self.import_repo.update_row(row, normalized_data=nd)
