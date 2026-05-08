"""Cluster-level bulk-apply for the import moderator (spec §5.4, §6.2, §10.2 case B).

A single moderator action ("apply this category + counterparty to all 50
Pyaterochka rows") fans out into:

  • per-row update via the existing single-row path (`update_row`) so the
    validation / status contract stays identical;
  • cluster-bulk-ack stamp on each row (`cluster_bulk_acked_at`) so the
    commit path applies §10.2 case B weight (0.5);
  • one rule upsert per `(fingerprint, category_id)` group with a single
    `confirms_delta = group_size`. The strength counter advances in one
    step → the rule activates / generalizes for future sessions;
  • counterparty fingerprint bindings (§6.2) for every fingerprint in the
    cluster pointing at the chosen counterparty;
  • cross-account identifier bindings (phone / contract / iban / card —
    `card` only for transfer rows per §12.11).

Extracted from `import_service.py` 2026-04-29 as step 3 of the §1 backlog
god-object decomposition. The orchestrator is constructed per request and
relies on the calling `ImportService` for `update_row` (pass-through) and
`recalculate_summary` (computed against the same DB session).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository
from app.schemas.imports import ImportRowUpdateRequest
from app.services.brand_fingerprint_service import BrandFingerprintService
from app.services.brand_identifier_service import (
    SUPPORTED_IDENTIFIER_KINDS,
    BrandIdentifierService,
)
from app.services.rule_strength_service import CONFIRM_WEIGHT_WARNING, RuleStrengthService


class BulkApplyOrchestrator:
    def __init__(
        self,
        db: Session,
        *,
        import_repo: ImportRepository,
        category_rule_repo: TransactionCategoryRuleRepository,
        update_row_fn: Callable[..., Any],
        recalculate_summary_fn: Callable[[int], dict[str, Any]],
        get_session_fn: Callable[..., Any],
    ) -> None:
        self.db = db
        self.import_repo = import_repo
        self.category_rule_repo = category_rule_repo
        # Phase C step 4: bindings go straight to the brand_*-tables.
        # CP-side binding services were removed.
        self._brand_fp_service = BrandFingerprintService(db)
        self._brand_id_service = BrandIdentifierService(db)
        # Pass-throughs so the orchestrator stays thin: update_row encodes the
        # full single-row contract; recalculate_summary already lives in
        # ImportService and looks up the session.
        self._update_row = update_row_fn
        self._recalculate_summary = recalculate_summary_fn
        self._get_session = get_session_fn

    def apply(
        self, *, user_id: int, session_id: int, payload: Any,
    ) -> dict[str, Any]:
        from app.core.config import settings

        session = self._get_session(user_id=user_id, session_id=session_id)

        skipped: list[int] = []
        # Rows keyed by (fingerprint, category_id) for rule upsert.
        by_rule_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
        confirmed_count = 0
        # A single cluster may span many fingerprints (brand cluster); one
        # brand choice binds all of them at once (§6.2).
        brand_bindings_by_brand: dict[int, set[str]] = {}
        # Cross-account identifier bindings — fingerprint bindings are scoped
        # to (account, bank), identifier bindings resolve the same recipient
        # across every statement.
        identifier_bindings_by_brand: dict[int, set[tuple[str, str]]] = {}

        for update in payload.updates:
            row_id = update.row_id
            session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
            if session_row is None:
                skipped.append(row_id)
                continue
            row_session, row = session_row
            if row_session.id != session.id:
                skipped.append(row_id)
                continue

            row_status = str(row.status or "").strip().lower()
            if row.created_transaction_id is not None or row_status == "committed":
                skipped.append(row_id)
                continue

            # Phase C step 5: brand_id is the only merchant binding key.
            # The legacy counterparty_id-to-brand resolver was removed
            # alongside the Counterparty table.
            update_brand_id = getattr(update, "brand_id", None)

            row_payload = ImportRowUpdateRequest(
                operation_type=update.operation_type,
                category_id=update.category_id,
                brand_id=update_brand_id,
                debt_partner_id=update.debt_partner_id,
                target_account_id=update.target_account_id,
                credit_account_id=update.credit_account_id,
                credit_principal_amount=update.credit_principal_amount,
                credit_interest_amount=update.credit_interest_amount,
                debt_direction=update.debt_direction,
                action="confirm",
            )
            self._update_row(user_id=user_id, row_id=row_id, payload=row_payload)
            confirmed_count += 1

            # §5.4 / §10.2 (v1.1): stamp the row as cluster-bulk-acked so the
            # commit path can (a) let warning rows through and (b) apply the
            # 0.5 weight for case B. Individual-confirm path uses a different
            # flag (`user_confirmed_at`, set in update_row) → weight 1.0.
            _fresh_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
            if _fresh_row is not None:
                _, _fresh = _fresh_row
                _fresh_norm = dict(
                    getattr(_fresh, "normalized_data", None) or (_fresh.normalized_data_json or {})
                )
                _fresh_norm["cluster_bulk_acked_at"] = datetime.now(timezone.utc).isoformat()
                _fresh_norm.pop("user_confirmed_at", None)
                self.import_repo.update_row(_fresh, normalized_data=_fresh_norm)

            # Collect rule-upsert buckets. Only rows with a non-None category
            # qualify — transfer/debt/credit rows without category_id don't
            # participate in category-rule learning.
            normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))
            fp = normalized.get("fingerprint")
            normalized_desc = normalized.get("skeleton") or ""
            original_desc = (
                normalized.get("import_original_description")
                or normalized.get("description")
            )
            if fp and update.category_id is not None and normalized_desc:
                # Этап 2: bucket key includes operation_type. A mixed cluster
                # (e.g. user splits 50 rows into 30 regular + 20 debt) used to
                # collapse into one rule that learned only the category.
                # Now each (fp, cat, op_type) combination upserts its own rule
                # so the op_type signal is preserved per learned shape. UI is
                # unchanged — the user still sees one cluster; the backend
                # silently materializes 1..N rules.
                bucket_op_type = (
                    str(update.operation_type).strip()
                    if update.operation_type is not None
                    else None
                ) or None
                by_rule_key.setdefault(
                    (fp, int(update.category_id), bucket_op_type), [],
                ).append({
                    "normalized_description": normalized_desc,
                    "original_description": original_desc,
                })

            # Resolved above when building row_payload — re-use it.
            row_brand_id = (
                int(update_brand_id) if update_brand_id not in (None, "", 0) else None
            )

            # Phase C step 4: fingerprint → Brand binding. Every fingerprint
            # in the cluster gets bound so future imports of ANY skeleton
            # resolve to the same brand automatically. Counterparty
            # binding is gone — brand_fingerprints is the only target.
            if fp and row_brand_id is not None:
                brand_bindings_by_brand.setdefault(row_brand_id, set()).add(fp)

            # Cross-account identifier binding. Pull the strongest token off
            # the row's normalized payload using the cluster-assembly priority
            # (contract > phone > iban > card). Skip unknown kinds.
            #
            # `card` binding is created ONLY for transfer rows (§12.11). In
            # Russian bank statements "Операция по карте ****7123" refers to
            # the PAYER'S card, not the merchant's. Binding a payer card to a
            # brand would pull every purchase made with that card under
            # the same brand. For transfers, the card token IS the
            # recipient's card and is a valid cross-account key.
            if row_brand_id is not None:
                row_op_type = str(normalized.get("operation_type") or "").lower()
                tokens = normalized.get("tokens") or {}
                if isinstance(tokens, dict):
                    for kind in ("contract", "phone", "iban", "card"):
                        value = tokens.get(kind)
                        if not value or kind not in SUPPORTED_IDENTIFIER_KINDS:
                            continue
                        if kind == "card" and row_op_type != "transfer":
                            continue
                        identifier_bindings_by_brand.setdefault(
                            row_brand_id, set()
                        ).add((kind, str(value)))
                        break

        # §10.2 case B: cluster-level bulk-ack adds confirms with weight 0.5
        # per row (not 1.0). A 92-row Pyaterochka cluster → +46.0 confirms in
        # one transition. The commit path won't re-count these rows — the
        # `cluster_bulk_acked_at` flag stamped above tells commit "already
        # accounted for, pass through without touching strength counters".
        rules_affected = 0
        strength_svc = RuleStrengthService(self.db, settings)
        for (_fp, category_id, bucket_op_type), rows_for_rule in by_rule_key.items():
            if not rows_for_rule:
                continue
            sample = rows_for_rule[0]
            bulk_weight = CONFIRM_WEIGHT_WARNING * Decimal(len(rows_for_rule))
            rule, _is_new = self.category_rule_repo.bulk_upsert(
                user_id=user_id,
                normalized_description=sample["normalized_description"],
                category_id=category_id,
                confirms_delta=len(rows_for_rule),
                original_description=sample["original_description"],
                operation_type=bucket_op_type,
            )
            strength_svc.on_confirmed(rule.id, confirms_delta=bulk_weight)
            rules_affected += 1

        # Persist brand bindings (accumulates across bulk-apply calls).
        # Phase C step 4 wrote the CP-side bindings out — brand_*-tables
        # are now the only home.
        brand_bindings_count = 0
        for brand_id, fps in brand_bindings_by_brand.items():
            brand_bindings_count += self._brand_fp_service.bind_many(
                user_id=user_id,
                fingerprints=list(fps),
                brand_id=brand_id,
            )
        for brand_id, pairs in identifier_bindings_by_brand.items():
            self._brand_id_service.bind_many(
                user_id=user_id,
                pairs=list(pairs),
                brand_id=brand_id,
            )

        self.db.commit()

        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()

        return {
            "session_id": session.id,
            "confirmed_count": confirmed_count,
            "skipped_row_ids": skipped,
            "rules_affected": rules_affected,
            "summary": summary,
        }
