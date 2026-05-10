"""Post-processors for the import preview pipeline.

Four deterministic, idempotent passes that run after normalization and
enrichment but before the rows are written to disk:

1. `gate_transfer_integrity` — §12.1 / §5.2 trigger 6 — escalate transfers
   with only one known account to `warning` (preview) or `error` (commit/edit).
2. `apply_refund_matches` — pair expense+income within the session via
   `RefundMatcherService` (§5.5) and stamp metadata on both sides.
3. `apply_refund_cluster_overrides` — for every refund cluster, push
   counterparty + dominant-category from purchase history onto member rows
   (compensator model).
4. `apply_bank_mechanics` — propagate cluster-level bank-mechanics results
   to individual rows: auto-exclude Яндекс Сплит phantom-mirror rows
   (suggest_exclude), stamp resolved target_account_id on Яндекс Дебет
   transfer rows (§9.10 / §6.9).

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
                # Phase C step 4: stamp the resolved brand id from the
                # refund-history JOIN. Older rows that were already
                # carrying nd.counterparty_id keep it as-is — step 5 sweeps
                # those off when it drops the column.
                if cluster.refund_resolved_brand_id is not None:
                    existing_brand = nd.get("brand_id")
                    if existing_brand in (None, "", 0):
                        nd["brand_id"] = int(cluster.refund_resolved_brand_id)
                self.import_repo.update_row(row, normalized_data=nd)

    # ------------------------------------------------------------------
    # 4. Bank-mechanics post-process (§9.10 / §6.9)
    # ------------------------------------------------------------------

    def apply_bank_mechanics(self, *, session: ImportSession) -> None:
        """Propagate cluster-level bank-mechanics results to ImportRows.

        Two effects, applied only when the row has not been explicitly
        confirmed by the user (guarded by `user_confirmed_at`):

        1. `suggest_exclude=True` — set `bank_mechanics_pending_exclude=True`
           on the row's normalized_data and (if missing) `operation_type='transfer'`.
           Status is NOT changed here. The cross-session transfer matcher runs
           after this pass; if it pairs the row with a debit-side counterpart
           (cross_session pair, §12.10) or marks it duplicate against a
           committed phantom income (branch B, §8.5), the pending flag is
           cleared by `finalize_bank_mechanics_exclusions` and the row stays
           visible in «Переводы и дубли» with the partner link. Only if the
           matcher couldn't find a pair does finalize set `status='excluded'`
           as a fallback safety net (avoids double-credit when the user
           imports only the credit-side statement).

        2. `resolved_target_account_id` — stamp `target_account_id` onto
           Яндекс Дебет transfer rows so the user does not have to pick the
           Сплит counter-account manually (account resolved from the
           contract token in the cluster's identifier at cluster-build time).

        Idempotent + rehabilitates legacy excluded rows: if a row is currently
        `status='excluded'` from the pre-deferral version of this method (no
        `bank_mechanics_pending_exclude` flag, no `created_transaction_id`,
        op='transfer', and the cluster still says suggest_exclude), reset
        status to 'ready' and stamp the pending flag so the matcher gets a
        fresh chance to pair it.
        """
        from app.services.import_cluster_service import ImportClusterService

        cluster_svc = ImportClusterService(self.db)
        clusters = cluster_svc.build_clusters(session)

        # Include clusters with ANY bank-mechanics signal:
        # • suggest_exclude — phantom-mirror auto-exclusion (Yandex Сплит
        #   income side of a Дебет-paid repayment).
        # • resolved_target_account_id — Дебет→Сплит transfer with target
        #   resolved from contract token.
        # • bank_mechanics_operation_type — rule fired with op-override
        #   (e.g. Yandex Сплит «погашение тела долга» expense → transfer)
        #   but contract token absent on the credit-side row, so target
        #   stays None. Without this branch, the cluster's op-decision
        #   wouldn't reach the row and it would render as «Обычная»; the
        #   cross-session matcher pairs the credit-side later.
        mechanic_clusters = [
            c for c in clusters
            if c.bank_mechanics_suggest_exclude
            or c.bank_mechanics_resolved_target_account_id is not None
            or c.bank_mechanics_operation_type is not None
        ]
        if not mechanic_clusters:
            return

        rows_by_id: dict[int, ImportRow] = {
            r.id: r for r in self.import_repo.get_rows(session_id=session.id)
        }

        for cluster in mechanic_clusters:
            for row_id in cluster.row_ids:
                row = rows_by_id.get(row_id)
                if row is None:
                    continue

                nd = dict(row.normalized_data_json or {})

                # Guard: user explicitly confirmed this row → preserve choice.
                if nd.get("user_confirmed_at"):
                    continue

                # Terminal statuses are not modified.
                if str(row.status or "").lower() in ("committed", "parked"):
                    continue

                nd_changed = False
                new_status: str | None = None

                if cluster.bank_mechanics_suggest_exclude:
                    # Defer the actual exclusion until after the cross-session
                    # transfer matcher runs (see `finalize_bank_mechanics_exclusions`).
                    if not nd.get("bank_mechanics_pending_exclude"):
                        nd["bank_mechanics_pending_exclude"] = True
                        nd_changed = True
                    # The phantom-mirror is logically a transfer between Дебет
                    # and credit accounts; tag op_type so the matcher and §12.10
                    # cross-session pair logic recognize it.
                    if str(nd.get("operation_type") or "") not in ("transfer",):
                        nd["operation_type"] = "transfer"
                        nd_changed = True
                    # Rehabilitate rows excluded by the pre-deferral version of
                    # this method: if the row is uncommitted and currently
                    # status='excluded', return it to 'ready' so the matcher
                    # can examine it. The pending flag (set above) ensures the
                    # exclusion is re-applied later if no pair is found.
                    if (
                        str(row.status or "").lower() == "excluded"
                        and getattr(row, "created_transaction_id", None) is None
                    ):
                        new_status = "ready"

                if (
                    cluster.bank_mechanics_resolved_target_account_id is not None
                    and nd.get("target_account_id") in (None, "", 0)
                ):
                    nd["target_account_id"] = cluster.bank_mechanics_resolved_target_account_id
                    if nd.get("operation_type") != "transfer":
                        nd["operation_type"] = "transfer"
                    # Clear credit-split flag: bank_mechanics resolved this row
                    # as a simple inter-account transfer (Ozon дебет → кредитка).
                    # requires_credit_split=True was set by _CREDIT_PAYMENT_KEYWORDS
                    # matching "погашение кредита", but that flag conflicts with the
                    # bank_mechanics decision — a resolved transfer has no split.
                    # Without clearing it, isTransferOrDuplicate returns false and
                    # the row lands in "Проверено" instead of "Переводы и дубли".
                    nd["requires_credit_split"] = False
                    nd["credit_account_id"] = None
                    nd["credit_principal_amount"] = None
                    nd["credit_interest_amount"] = None
                    nd_changed = True
                    # A transfer with both accounts resolved is valid — upgrade
                    # 'warning' to 'ready' so it appears correctly in the UI.
                    if str(row.status or "") == "warning" and not new_status:
                        new_status = "ready"

                # Op-override without target: e.g. Yandex Сплит credit-side
                # «погашение тела долга» expense — bank_mechanics knows it's
                # a transfer but only the Дебет side carries the contract,
                # so we can't resolve target here. Stamp op_type anyway so
                # the cross-session matcher recognises this as a pair
                # candidate; the user sees «Перевод» in the UI instead of
                # the misleading «Обычная».
                if (
                    cluster.bank_mechanics_operation_type
                    and nd.get("operation_type") != cluster.bank_mechanics_operation_type
                    and not nd.get("target_account_id")
                ):
                    nd["operation_type"] = cluster.bank_mechanics_operation_type
                    nd_changed = True

                # Stamp the human-readable label so the moderator UI can
                # show «Сработало правило: Яндекс: погашение тела долга»
                # and the user understands WHY the row was classified.
                if cluster.bank_mechanics_label and nd.get("bank_mechanics_label") != cluster.bank_mechanics_label:
                    nd["bank_mechanics_label"] = cluster.bank_mechanics_label
                    nd_changed = True

                if new_status or nd_changed:
                    kwargs: dict[str, Any] = {}
                    if new_status:
                        kwargs["status"] = new_status
                    if nd_changed:
                        kwargs["normalized_data"] = nd
                    self.import_repo.update_row(row, **kwargs)

    # ------------------------------------------------------------------
    # 5. Finalize bank-mechanics exclusions (post-matcher, §9.10 / §12.10)
    # ------------------------------------------------------------------

    def finalize_bank_mechanics_exclusions(self, *, user_id: int) -> None:
        """Resolve `bank_mechanics_pending_exclude` flags after the
        cross-session transfer matcher has had its turn.

        For every active row of `user_id` carrying the pending flag:
          • If `transfer_match` is now present (matcher paired the row with a
            debit-side counterpart, §12.10, or marked it duplicate against a
            committed phantom-income tx, §8.5 branch B) — clear the pending
            flag and leave status alone. The matcher already chose the
            correct status ('ready' for cross-session pair, 'duplicate' for
            committed phantom).
          • Otherwise — set status='excluded' (the original safety net,
            §9.10): the credit-side phantom-mirror has no paired Дебет row in
            any active or committed scope, so committing it would
            double-credit the credit account when the Дебет statement is
            eventually imported.

        Idempotent: runs once per matcher cycle, no-op when there are no
        rows with the pending flag.
        """
        rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
            )
            .all()
        )

        for row in rows:
            nd = dict(row.normalized_data_json or {})
            if not nd.get("bank_mechanics_pending_exclude"):
                continue
            # Don't touch terminal/committed rows.
            if str(row.status or "").lower() in ("committed", "parked"):
                continue
            # Respect explicit user confirmation: if the user already confirmed
            # this row (e.g. via UI override), leave it alone. Clearing the
            # flag prevents future runs from re-evaluating.
            if nd.get("user_confirmed_at"):
                nd.pop("bank_mechanics_pending_exclude", None)
                self.import_repo.update_row(row, normalized_data=nd)
                continue

            paired = bool(nd.get("transfer_match"))
            nd.pop("bank_mechanics_pending_exclude", None)

            if paired:
                # Matcher attached a partner — keep its status decision and
                # clear the pending flag.
                self.import_repo.update_row(row, normalized_data=nd)
            else:
                # Matcher didn't find a pair — fall back to the original
                # auto-exclude behavior so the credit balance isn't doubled
                # when the Дебет statement arrives later.
                self.import_repo.update_row(
                    row, normalized_data=nd, status="excluded",
                )
