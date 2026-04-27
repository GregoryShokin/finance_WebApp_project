from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction as TransactionModel
from app.repositories.account_repository import AccountRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.imports import ImportMappingRequest, ImportPreviewSummary, ImportRowUpdateRequest
from app.services.counterparty_fingerprint_service import CounterpartyFingerprintService
from app.services.counterparty_identifier_service import (
    SUPPORTED_IDENTIFIER_KINDS,
    CounterpartyIdentifierService,
)
from app.services.fingerprint_alias_service import FingerprintAliasService
from app.services.import_confidence import ImportConfidenceService
from app.services.import_extractors import ExtractionResult, ImportExtractorRegistry
from app.schemas.import_normalized import NormalizedDataV2
from app.services.import_normalizer import ImportNormalizer
from app.services.import_normalizer_v2 import (
    extract_tokens as v2_extract_tokens,
    fingerprint as v2_fingerprint,
    is_refund_like as v2_is_refund_like,
    is_transfer_like as v2_is_transfer_like,
    normalize_skeleton as v2_normalize_skeleton,
    pick_refund_brand as v2_pick_refund_brand,
    pick_transfer_identifier as v2_pick_transfer_identifier,
)
from app.services.import_recognition_service import ImportRecognitionService
from app.services.import_validator import ImportRowValidationError
from app.services.transaction_enrichment_service import (
    ALLOWED_OPERATION_TYPES,
    TransactionEnrichmentService,
)
from app.services.transaction_service import NON_ANALYTICS_OPERATION_TYPES, TransactionService, TransactionValidationError
from app.services.rule_strength_service import RuleNotFound, RuleStrengthService
from app.services.transfer_matcher_service import TransferMatcherService
from app.services.refund_matcher_service import RefundMatcherService


logger = logging.getLogger(__name__)

RAW_TYPE_TO_OPERATION_TYPE = {
    "purchase": "regular",
    "transfer": "transfer",
    "investment_buy": "investment_buy",
    "investment_sell": "investment_sell",
    "credit_disbursement": "credit_disbursement",
    # §9.1 / §12.3: "credit_payment" is not a valid operation_type. A loan
    # payment is stored in normalized_data as a transfer whose commit step
    # splits it into (interest expense + principal transfer). The
    # `requires_credit_split` flag on normalized_data is the meta-signal
    # that drives the split-form in the moderator UI and the commit branch.
    "credit_payment": "transfer",
    "credit_interest": "regular",
}

# Raw-type values that, on top of their normal operation_type mapping, also
# flag the row for the credit split-form UI / commit-time split handling.
_RAW_TYPES_REQUIRING_CREDIT_SPLIT = {"credit_payment"}


class ImportValidationError(Exception):
    pass


class ImportNotFoundError(Exception):
    pass


class ImportService:
    def __init__(self, db: Session):
        self.db = db
        self.import_repo = ImportRepository(db)
        self.transaction_repo = TransactionRepository(db)
        self.account_repo = AccountRepository(db)
        self.extractors = ImportExtractorRegistry()
        self.recognition_service = ImportRecognitionService()
        self.normalizer = ImportNormalizer()
        self.confidence = ImportConfidenceService()
        self.enrichment = TransactionEnrichmentService(db)
        self.transaction_service = TransactionService(db)
        self.category_rule_repo = TransactionCategoryRuleRepository(db)
        self.transfer_matcher = TransferMatcherService(db)
        self._alias_service = FingerprintAliasService(db)
        self._counterparty_fp_service = CounterpartyFingerprintService(db)
        self._counterparty_id_service = CounterpartyIdentifierService(db)

    def upload_source(
        self,
        *,
        user_id: int,
        filename: str,
        raw_bytes: bytes,
        delimiter: str | None = None,
        has_header: bool = True,
    ) -> dict[str, Any]:
        return self.upload_file(
            user_id=user_id,
            filename=filename,
            raw_bytes=raw_bytes,
            delimiter=delimiter,
            has_header=has_header,
        )

    def upload_file(
        self,
        *,
        user_id: int,
        filename: str,
        raw_bytes: bytes,
        delimiter: str | None = None,
        has_header: bool = True,
    ) -> dict[str, Any]:
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        existing = self.import_repo.find_active_by_file_hash(user_id=user_id, file_hash=file_hash)
        if existing is not None:
            return self._session_to_upload_response(existing)

        extension = self._detect_extension(filename)
        extractor = self.extractors.get(extension)
        if extractor is None:
            raise ImportValidationError(f"Р¤РѕСЂРјР°С‚ .{extension} РЅРµ РїРѕРґРґРµСЂР¶РёРІР°РµС‚СЃСЏ РґР»СЏ РёРјРїРѕСЂС‚Р°.")

        try:
            extraction = extractor.extract(
                filename=filename,
                raw_bytes=raw_bytes,
                options={"delimiter": delimiter, "has_header": has_header},
            )
        except Exception as exc:
            raise ImportValidationError(f"РќРµ СѓРґР°Р»РѕСЃСЊ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ С„Р°Р№Р» {filename}: {exc}") from exc

        if not extraction.tables:
            raise ImportValidationError("РќРµ СѓРґР°Р»РѕСЃСЊ РёР·РІР»РµС‡СЊ РґР°РЅРЅС‹Рµ РёР· С„Р°Р№Р»Р°.")

        primary_table = self._pick_primary_table(extraction)
        detection = self.recognition_service.recognize(table=primary_table)
        contract_number = extraction.meta.get("contract_number")
        contract_match_reason = extraction.meta.get("contract_match_reason")
        contract_match_confidence = extraction.meta.get("contract_match_confidence")
        statement_account_number = extraction.meta.get("statement_account_number")
        statement_account_match_reason = extraction.meta.get("statement_account_match_reason")
        statement_account_match_confidence = extraction.meta.get("statement_account_match_confidence")
        suggested_account_id = None

        if contract_number and user_id:
            matched_account = self.account_repo.find_by_contract_number(
                user_id=user_id,
                contract_number=contract_number,
            )
            if matched_account:
                suggested_account_id = matched_account.id

        if suggested_account_id is None and statement_account_number and user_id:
            matched_account = self.account_repo.find_by_statement_account_number(
                user_id=user_id,
                statement_account_number=statement_account_number,
            )
            if matched_account:
                suggested_account_id = matched_account.id

        storage_payload = self._encode_source(raw_bytes=raw_bytes, source_type=extension)
        parse_settings = {
            "delimiter": delimiter,
            "has_header": has_header,
            "storage": storage_payload["storage"],
            "source_extension": extension,
            "extraction": extraction.meta,
            "table_names": [table.name for table in extraction.tables],
            "table_row_counts": {table.name: len(table.rows) for table in extraction.tables},
            "tables": self._serialize_tables(extraction.tables),
            "detection": detection,
            "contract_number": contract_number,
            "statement_account_number": statement_account_number,
        }

        session = self.import_repo.create_session(
            user_id=user_id,
            filename=filename,
            file_content=storage_payload["content"],
            detected_columns=primary_table.columns,
            parse_settings=parse_settings,
            source_type=extension,
        )
        session.file_hash = file_hash
        self.import_repo.update_session(
            session,
            status="analyzed",
            mapping_json=detection,
            summary_json={},
            account_id=suggested_account_id,
        )
        self.db.commit()
        self.db.refresh(session)

        # If the uploader detected both an account and a usable field mapping,
        # auto-build the preview in the background. This is what makes the
        # queue-level transfer matcher work end-to-end: every session gets rows
        # shortly after upload, so when the Nth statement lands the matcher
        # can find cross-bank pairs without the user previewing each session.
        field_mapping = (detection or {}).get("field_mapping") or {}
        if suggested_account_id is not None and field_mapping.get("date") and field_mapping.get("amount"):
            try:
                from app.jobs.auto_preview_import_session import auto_preview_import_session
                auto_preview_import_session.delay(session.id)
            except Exception:
                logger.exception("auto_preview_import_session enqueue failed for session %s", session.id)

        return {
            "session_id": session.id,
            "filename": session.filename,
            "source_type": session.source_type,
            "status": session.status,
            "detected_columns": primary_table.columns,
            "sample_rows": primary_table.rows[:5],
            "total_rows": len(primary_table.rows),
            "extraction": {
                **extraction.meta,
                "tables_found": len(extraction.tables),
                "primary_table": primary_table.name,
            },
            "detection": detection,
            "suggested_account_id": suggested_account_id,
            "contract_number": contract_number,
            "contract_match_reason": contract_match_reason,
            "contract_match_confidence": contract_match_confidence,
            "statement_account_number": statement_account_number,
            "statement_account_match_reason": statement_account_match_reason,
            "statement_account_match_confidence": statement_account_match_confidence,
        }

    def get_session(self, *, user_id: int, session_id: int) -> ImportSession:
        session = self.import_repo.get_session(session_id=session_id, user_id=user_id)
        if session is None:
            raise ImportNotFoundError("РЎРµСЃСЃРёСЏ РёРјРїРѕСЂС‚Р° РЅРµ РЅР°Р№РґРµРЅР°.")
        return session

    def get_bulk_clusters(self, *, user_id: int, session_id: int) -> dict[str, Any]:
        """Return bulk-eligible fingerprint clusters + brand groups for the wizard.

        See project_bulk_clusters.md for the hierarchy contract. The wizard
        merges brand groups with their member fingerprints client-side — we
        return both as flat lists to keep the payload diffable.
        """
        from app.services.import_cluster_service import ImportClusterService

        session = self.get_session(user_id=user_id, session_id=session_id)
        cluster_svc = ImportClusterService(self.db)
        fp_clusters, brand_clusters, counterparty_groups = cluster_svc.build_bulk_clusters(session)

        fp_dicts = []
        for c in fp_clusters:
            fp_dicts.append({
                "fingerprint": c.fingerprint,
                "count": c.count,
                "total_amount": c.total_amount,
                "direction": c.direction,
                "skeleton": c.skeleton,
                "row_ids": list(c.row_ids),
                "candidate_category_id": c.candidate_category_id,
                "candidate_rule_id": c.candidate_rule_id,
                "rule_source": c.rule_source,
                "confidence": c.confidence,
                "trust_zone": c.trust_zone,
                "auto_trust": c.auto_trust,
                "identifier_key": c.identifier_key,
                "identifier_value": c.identifier_value,
            })
        brand_dicts = [b.to_dict() for b in brand_clusters]
        counterparty_dicts = [g.to_dict() for g in counterparty_groups]
        return {
            "session_id": session.id,
            "fingerprint_clusters": fp_dicts,
            "brand_clusters": brand_dicts,
            "counterparty_groups": counterparty_dicts,
        }

    def bulk_apply_cluster(
        self, *, user_id: int, session_id: int, payload: Any,
    ) -> dict[str, Any]:
        """Apply one moderator action across many rows in a cluster.

        Per row: reuses the single-row update path (action="confirm") so the
        validation/status contract stays identical. Rows already turned into
        Transactions are skipped and returned in `skipped_row_ids` — the
        race-condition guard from project_bulk_clusters.md.

        After row updates, groups confirmed rows by `(fingerprint, category_id)`
        and upserts a rule per group with `confirms_delta = group_size`. The
        rule's strength counters advance in one step, which activates /
        generalizes it immediately for future sessions.
        """
        from app.core.config import settings
        session = self.get_session(user_id=user_id, session_id=session_id)

        skipped: list[int] = []
        # Rows keyed by (fingerprint, category_id) for rule upsert.
        by_rule_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
        confirmed_count = 0
        # Phase 3 — collect fingerprints to bind to a counterparty.
        # A single cluster may span many fingerprints (brand cluster), and one
        # counterparty choice binds all of them at once.
        counterparty_bindings_by_cp: dict[int, set[str]] = {}
        # Cross-account identifier bindings (phone/contract/iban/card →
        # counterparty). Fingerprint bindings are account-scoped because the
        # fingerprint itself bakes in account_id + bank; identifier bindings
        # resolve the same recipient across every statement.
        identifier_bindings_by_cp: dict[int, set[tuple[str, str]]] = {}

        for update in payload.updates:
            row_id = update.row_id
            session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
            if session_row is None:
                # Silently skip rows that don't belong to this user — caller
                # shouldn't know about them. They won't count as confirmed.
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

            row_payload = ImportRowUpdateRequest(
                operation_type=update.operation_type,
                category_id=update.category_id,
                counterparty_id=update.counterparty_id,
                debt_partner_id=update.debt_partner_id,
                target_account_id=update.target_account_id,
                credit_account_id=update.credit_account_id,
                credit_principal_amount=update.credit_principal_amount,
                credit_interest_amount=update.credit_interest_amount,
                debt_direction=update.debt_direction,
                action="confirm",
            )
            self.update_row(user_id=user_id, row_id=row_id, payload=row_payload)
            confirmed_count += 1

            # §5.4 / §10.2 (v1.1): stamp the row as cluster-bulk-acked so the
            # commit path can (a) let warning rows through and (b) apply the
            # 0.5 weight for Case B. Individual-confirm path uses a different
            # flag (`user_confirmed_at`, set in update_row) → weight 1.0.
            from datetime import datetime, timezone
            _fresh_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
            if _fresh_row is not None:
                _, _fresh = _fresh_row
                _fresh_norm = dict(
                    getattr(_fresh, "normalized_data", None) or (_fresh.normalized_data_json or {})
                )
                _fresh_norm["cluster_bulk_acked_at"] = datetime.now(timezone.utc).isoformat()
                # Explicitly clear user_confirmed_at — cluster-ack supersedes
                # any stale individual-confirm mark from a previous edit pass.
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
                by_rule_key.setdefault((fp, int(update.category_id)), []).append({
                    "normalized_description": normalized_desc,
                    "original_description": original_desc,
                })

            # Phase 3 — fingerprint → counterparty binding. When the user
            # picks a counterparty for a cluster, every fingerprint in the
            # cluster gets bound so future imports of ANY of its skeletons
            # resolve to the same counterparty automatically.
            if fp and update.counterparty_id is not None:
                counterparty_bindings_by_cp.setdefault(
                    int(update.counterparty_id), set()
                ).add(fp)

            # Cross-account identifier binding. Pull the strongest token off
            # the row's normalized payload — matching the priority used by
            # cluster assembly (contract > phone > iban > card). Skip unknown
            # kinds; they're not cross-account-safe.
            #
            # `card` binding is only created for transfer rows. In Russian bank
            # statements "Операция по карте ****7123" refers to the PAYER'S own
            # card (the account being imported), NOT the merchant's card. Binding
            # that card number to a counterparty would pull every purchase made
            # with the same card under that counterparty. For transfers, the card
            # token IS the recipient's card and is a valid cross-account key.
            if update.counterparty_id is not None:
                row_op_type = str(normalized.get("operation_type") or "").lower()
                tokens = normalized.get("tokens") or {}
                if isinstance(tokens, dict):
                    for kind in ("contract", "phone", "iban", "card"):
                        value = tokens.get(kind)
                        if not value or kind not in SUPPORTED_IDENTIFIER_KINDS:
                            continue
                        if kind == "card" and row_op_type != "transfer":
                            continue
                        identifier_bindings_by_cp.setdefault(
                            int(update.counterparty_id), set()
                        ).add((kind, str(value)))
                        break

        # §10.2 Case B: cluster-level bulk-ack adds confirms with weight 0.5
        # per row (not 1.0). A 92-row Pyaterochka cluster → +46.0 confirms
        # in one transition. The commit path won't re-count these rows — the
        # `cluster_bulk_acked_at` flag stamped above tells commit "already
        # accounted for, pass through without touching strength counters".
        from decimal import Decimal as _D
        from app.services.rule_strength_service import CONFIRM_WEIGHT_WARNING
        rules_affected = 0
        strength_svc = RuleStrengthService(self.db, settings)
        for (_fp, category_id), rows_for_rule in by_rule_key.items():
            if not rows_for_rule:
                continue
            sample = rows_for_rule[0]
            bulk_weight = CONFIRM_WEIGHT_WARNING * _D(len(rows_for_rule))
            rule, _is_new = self.category_rule_repo.bulk_upsert(
                user_id=user_id,
                normalized_description=sample["normalized_description"],
                category_id=category_id,
                confirms_delta=len(rows_for_rule),
                original_description=sample["original_description"],
            )
            strength_svc.on_confirmed(rule.id, confirms_delta=bulk_weight)
            rules_affected += 1

        # Phase 3 — persist counterparty bindings. Bindings accumulate across
        # bulk-apply calls so a brand that lives in 5 different fingerprints
        # gets all 5 bound to the same counterparty after one confirmation.
        counterparty_bindings_count = 0
        for cp_id, fps in counterparty_bindings_by_cp.items():
            counterparty_bindings_count += self._counterparty_fp_service.bind_many(
                user_id=user_id,
                fingerprints=list(fps),
                counterparty_id=cp_id,
            )
        # Identifier bindings — cross-account layer. Same counterparty may have
        # several identifiers (e.g. different phones for different services of
        # the same vendor); each pair is stored independently.
        for cp_id, pairs in identifier_bindings_by_cp.items():
            self._counterparty_id_service.bind_many(
                user_id=user_id,
                pairs=list(pairs),
                counterparty_id=cp_id,
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

    def attach_row_to_cluster(
        self,
        *,
        user_id: int,
        session_id: int,
        row_id: int,
        target_fingerprint: str | None = None,
        counterparty_id: int | None = None,
    ) -> dict[str, Any]:
        """Attach a row to a counterparty (Phase 3) or an existing cluster.

        Exactly one of `counterparty_id` / `target_fingerprint` must be set.

        Counterparty path (preferred):
          1. Verify counterparty belongs to the user.
          2. Try to resolve a category from the counterparty's existing
             bindings (look at other fingerprints bound to this counterparty
             in any of the user's sessions — take the category from the most
             common rule).
          3. Create `CounterpartyFingerprint(source_fp → counterparty_id)`.
          4. Commit the row with that category + counterparty.

        Fingerprint path (legacy):
          1. Resolve target cluster's metadata from this session's rows or
             from a rule matching the target's skeleton.
          2. Create FingerprintAlias(source_fp → target_fp).
          3. Commit the row as a Transaction.

        Raises ImportValidationError on any precondition failure.
        """
        if counterparty_id is None and not target_fingerprint:
            raise ImportValidationError(
                "Нужно указать контрагента или целевой кластер"
            )
        if counterparty_id is not None and target_fingerprint:
            raise ImportValidationError(
                "Нельзя указать одновременно контрагента и кластер"
            )

        session = self.get_session(user_id=user_id, session_id=session_id)
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError(f"import row {row_id} not found")
        row_session, row = session_row
        if row_session.id != session.id:
            raise ImportNotFoundError(f"import row {row_id} not in session {session_id}")

        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Строка уже импортирована")

        normalized = dict(row.normalized_data_json or {})
        source_fp = normalized.get("fingerprint") or (normalized.get("v2") or {}).get("fingerprint")
        if not source_fp:
            raise ImportValidationError(
                "У строки нет fingerprint — пересобери preview и попробуй ещё раз"
            )

        if counterparty_id is not None:
            return self._attach_via_counterparty(
                user_id=user_id,
                session=session,
                row=row,
                row_id=row_id,
                source_fp=source_fp,
                normalized=normalized,
                counterparty_id=counterparty_id,
            )
        return self._attach_via_fingerprint(
            user_id=user_id,
            session=session,
            row=row,
            row_id=row_id,
            source_fp=source_fp,
            normalized=normalized,
            target_fingerprint=target_fingerprint,
        )

    def _attach_via_counterparty(
        self,
        *,
        user_id: int,
        session: ImportSession,
        row: ImportRow,
        row_id: int,
        source_fp: str,
        normalized: dict[str, Any],
        counterparty_id: int,
    ) -> dict[str, Any]:
        # Counterparty must belong to the user.
        from app.models.counterparty import Counterparty
        cp = (
            self.db.query(Counterparty)
            .filter(Counterparty.id == counterparty_id, Counterparty.user_id == user_id)
            .first()
        )
        if cp is None:
            raise ImportNotFoundError(f"counterparty {counterparty_id} not found")

        # Resolve the counterparty's prevailing category. We look in three
        # progressively weaker sources:
        #   1. Committed transactions already tagged with this counterparty —
        #      ground truth, the user has confirmed these.
        #   2. Live preview rows across the user's active import sessions that
        #      are already pinned to this counterparty via their fingerprint
        #      binding and carry a candidate category_id. This covers the
        #      common case where the user tagged a cluster "Кофейни" in the
        #      current session but hasn't committed yet — the counterparty
        #      effectively has a category, it just isn't in `transactions`.
        #   3. The row's own cluster hint (candidate_category_id).
        # If none of these yield a category, the binding is still created —
        # the row just stays in the attention bucket for the user to classify
        # manually later. No "category required" block.
        target_category_id: int | None = None
        target_operation_type: str = "regular"

        from collections import Counter as _Counter
        from app.models.transaction import Transaction as _Transaction
        tx_cats = (
            self.db.query(_Transaction.category_id)
            .filter(
                _Transaction.user_id == user_id,
                _Transaction.counterparty_id == counterparty_id,
                _Transaction.category_id.isnot(None),
            )
            .all()
        )
        cat_votes: _Counter[int] = _Counter(
            int(r[0]) for r in tx_cats if r[0] is not None
        )
        if cat_votes:
            target_category_id = cat_votes.most_common(1)[0][0]

        # Source 2 — live preview rows across all active sessions. Find every
        # fingerprint already bound to this counterparty, then pull the
        # candidate category_id stamped on those rows' normalized_data.
        if target_category_id is None:
            bound_fps = self._counterparty_fp_service.repo.list_by_counterparty(
                user_id=user_id, counterparty_id=counterparty_id,
            )
            bound_fp_set = {b.fingerprint for b in bound_fps if b.fingerprint}

            if bound_fp_set:
                all_session_rows = (
                    self.db.query(ImportRow)
                    .join(ImportSession, ImportRow.session_id == ImportSession.id)
                    .filter(ImportSession.user_id == user_id)
                    .all()
                )
                preview_cat_votes: _Counter[int] = _Counter()
                for sess_row in all_session_rows:
                    nd = sess_row.normalized_data_json or {}
                    fp = nd.get("fingerprint") or (nd.get("v2") or {}).get("fingerprint")
                    if fp not in bound_fp_set:
                        continue
                    cat = nd.get("category_id")
                    if cat is None:
                        continue
                    try:
                        preview_cat_votes[int(cat)] += 1
                    except (TypeError, ValueError):
                        continue
                if preview_cat_votes:
                    target_category_id = preview_cat_votes.most_common(1)[0][0]

        # Source 3 — row's own cluster hint (candidate_category_id).
        if target_category_id is None:
            hint = normalized.get("category_id")
            if hint is not None:
                try:
                    target_category_id = int(hint)
                except (TypeError, ValueError):
                    target_category_id = None

        # Create the binding — the counterparty attachment happens regardless
        # of whether we resolved a category. The row just won't be marked
        # ready if category is still unknown.
        binding_created = False
        try:
            before = self._counterparty_fp_service.repo.get_by_fingerprint(
                user_id=user_id, fingerprint=source_fp,
            )
            self._counterparty_fp_service.bind(
                user_id=user_id,
                fingerprint=source_fp,
                counterparty_id=counterparty_id,
            )
            binding_created = before is None
        except ValueError as exc:
            raise ImportValidationError(str(exc)) from exc

        normalized["attached_to_counterparty_id"] = counterparty_id
        normalized["attached_to_counterparty_name"] = cp.name
        normalized["attached_source_fingerprint"] = source_fp
        # Clear the detached flag: the user is explicitly re-attaching this
        # row to a cluster (via its counterparty), so it must leave the
        # attention bucket and re-enter counterparty-group rendering.
        # Without clearing, build_bulk_clusters would still exclude the row
        # from every group — the counterparty card would gain a binding but
        # no visible member, and the user wouldn't find the row anywhere.
        normalized.pop("detached_from_cluster", None)
        row.normalized_data_json = normalized
        self.db.add(row)
        self.db.flush()

        # Preserve a refund classification if the row carries one — attach
        # must not silently demote a refund to a regular income row. The
        # refund's own category was set earlier (from purchase history) and
        # continues to win over `target_operation_type` we just computed
        # from the counterparty's tx history.
        existing_op = str(normalized.get("operation_type") or "").lower()
        effective_op = "refund" if existing_op == "refund" else target_operation_type

        # Only auto-confirm the row when a category was resolved. Without
        # a category the row must stay in the attention bucket so the user
        # can classify it before commit — we still persist the counterparty
        # binding and cluster attachment so next time a matching row comes
        # in, it lands with the counterparty pre-filled.
        if target_category_id is not None:
            row_payload = ImportRowUpdateRequest(
                operation_type=effective_op,
                category_id=target_category_id,
                counterparty_id=counterparty_id,
                action="confirm",
            )
        else:
            row_payload = ImportRowUpdateRequest(
                operation_type=effective_op,
                counterparty_id=counterparty_id,
            )
        self.update_row(user_id=user_id, row_id=row_id, payload=row_payload)

        self.db.commit()
        self.db.refresh(row)
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()

        return {
            "row_id": row_id,
            "transaction_id": row.created_transaction_id,
            "target_fingerprint": None,
            "counterparty_id": counterparty_id,
            "alias_created": False,
            "binding_created": binding_created,
            "source_fingerprint": source_fp,
            "summary": summary,
        }

    def _attach_via_fingerprint(
        self,
        *,
        user_id: int,
        session: ImportSession,
        row: ImportRow,
        row_id: int,
        source_fp: str,
        normalized: dict[str, Any],
        target_fingerprint: str,
    ) -> dict[str, Any]:
        if source_fp == target_fingerprint:
            raise ImportValidationError("Строка уже относится к этому кластеру")

        target_category_id: int | None = None
        target_counterparty_id: int | None = None
        target_operation_type: str | None = None
        target_skeleton: str | None = None

        all_rows = self.import_repo.list_rows(session_id=session.id)
        target_rows = []
        for candidate in all_rows:
            c_norm = candidate.normalized_data_json or {}
            c_fp = c_norm.get("fingerprint") or (c_norm.get("v2") or {}).get("fingerprint")
            if c_fp == target_fingerprint:
                target_rows.append((candidate, c_norm))

        if not target_rows:
            raise ImportValidationError("Целевой кластер не найден в этой сессии")

        for _candidate, c_norm in target_rows:
            cat = c_norm.get("category_id")
            if cat is not None:
                try:
                    target_category_id = int(cat)
                except (TypeError, ValueError):
                    continue
                target_counterparty_id = c_norm.get("counterparty_id")
                target_operation_type = c_norm.get("operation_type") or "regular"
                target_skeleton = c_norm.get("skeleton") or (c_norm.get("v2") or {}).get("skeleton")
                break

        if target_category_id is None:
            first_norm = target_rows[0][1]
            target_skeleton = first_norm.get("skeleton") or (first_norm.get("v2") or {}).get("skeleton")
            if target_skeleton:
                rule = self.category_rule_repo.get_best_rule(
                    user_id=user_id, normalized_description=target_skeleton,
                )
                if rule is not None and rule.category_id is not None:
                    target_category_id = int(rule.category_id)
                    target_operation_type = "regular"

        if target_category_id is None:
            raise ImportValidationError(
                "В целевом кластере ещё нет категории — сначала подтверди его"
            )

        alias_created = False
        try:
            self._alias_service.create_alias(
                user_id=user_id,
                source_fingerprint=source_fp,
                target_fingerprint=target_fingerprint,
            )
            alias_created = True
        except ValueError as exc:
            raise ImportValidationError(str(exc)) from exc

        if target_skeleton:
            normalized.setdefault("attached_to_skeleton", target_skeleton)
        normalized["attached_source_fingerprint"] = source_fp
        # Clear the detached flag — symmetric to _attach_via_counterparty.
        # Re-attaching to a target fingerprint/cluster must pull the row
        # back into cluster rendering; otherwise the alias is created but
        # build_bulk_clusters still excludes the row and the user can't
        # find it anywhere on screen.
        normalized.pop("detached_from_cluster", None)
        row.normalized_data_json = normalized
        self.db.add(row)
        self.db.flush()

        # Preserve refund classification across attach — same reason as in
        # _attach_via_counterparty.
        existing_op_fp = str(normalized.get("operation_type") or "").lower()
        effective_op_fp = (
            "refund" if existing_op_fp == "refund"
            else (target_operation_type or "regular")
        )

        row_payload = ImportRowUpdateRequest(
            operation_type=effective_op_fp,
            category_id=target_category_id,
            counterparty_id=target_counterparty_id,
            action="confirm",
        )
        self.update_row(user_id=user_id, row_id=row_id, payload=row_payload)

        self.db.commit()
        self.db.refresh(row)
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()

        return {
            "row_id": row_id,
            "transaction_id": row.created_transaction_id,
            "target_fingerprint": target_fingerprint,
            "counterparty_id": None,
            "alias_created": alias_created,
            "binding_created": False,
            "source_fingerprint": source_fp,
            "summary": summary,
        }

    def list_active_sessions(self, *, user_id: int) -> dict[str, Any]:
        sessions = self.import_repo.list_active_sessions(user_id=user_id)
        items = []
        for session in sessions:
            rows = self.import_repo.list_rows(session_id=session.id)
            summary = session.summary_json or {}
            auto_preview = (summary.get("auto_preview") or {}).get("status")
            transfer_match = (summary.get("transfer_match") or {}).get("status")
            items.append({
                "id": session.id,
                "filename": session.filename,
                "source_type": session.source_type,
                "status": session.status,
                "account_id": session.account_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "row_count": len(rows),
                "ready_count": sum(1 for r in rows if r.status == "ready"),
                "error_count": sum(1 for r in rows if r.status == "error"),
                "auto_preview_status": auto_preview,
                "transfer_match_status": transfer_match,
            })
        return {"sessions": items, "total": len(items)}

    def delete_session(self, *, user_id: int, session_id: int) -> None:
        session = self.import_repo.get_session(session_id=session_id, user_id=user_id)
        if session is None:
            raise ImportNotFoundError("РЎРµСЃСЃРёСЏ РёРјРїРѕСЂС‚Р° РЅРµ РЅР°Р№РґРµРЅР°.")
        self.import_repo.delete_session(session)
        self.db.commit()


    def send_row_to_review(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("РЎС‚СЂРѕРєР° РёРјРїРѕСЂС‚Р° РЅРµ РЅР°Р№РґРµРЅР°.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("РЎС‚СЂРѕРєР° СѓР¶Рµ РёРјРїРѕСЂС‚РёСЂРѕРІР°РЅР° Рё РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ РѕС‚РїСЂР°РІР»РµРЅР° РЅР° РїСЂРѕРІРµСЂРєСѓ.")
        if row_status == "duplicate":
            raise ImportValidationError("Р”СѓР±Р»РёРєР°С‚ РЅРµР»СЊР·СЏ РѕС‚РїСЂР°РІРёС‚СЊ РЅР° РїСЂРѕРІРµСЂРєСѓ РІСЂСѓС‡РЅСѓСЋ.")
        if row_status == "error":
            raise ImportValidationError("РЎС‚СЂРѕРєР° СѓР¶Рµ СЃРѕРґРµСЂР¶РёС‚ РѕС€РёР±РєСѓ Рё Р±СѓРґРµС‚ РґРѕСЃС‚СѓРїРЅР° РІ РїСЂРѕРІРµСЂРєРµ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.")
        if row_status != "ready":
            raise ImportValidationError("РќР° РїСЂРѕРІРµСЂРєСѓ РјРѕР¶РЅРѕ РѕС‚РїСЂР°РІРёС‚СЊ С‚РѕР»СЊРєРѕ СЃС‚СЂРѕРєРё СЃРѕ СЃС‚Р°С‚СѓСЃРѕРј 'Р“РѕС‚РѕРІРѕ'.")

        issues = list(dict.fromkeys([*(getattr(row, "errors", None) or []), "РћС‚РїСЂР°РІР»РµРЅРѕ РЅР° РїСЂРѕРІРµСЂРєСѓ РІСЂСѓС‡РЅСѓСЋ."]))
        row = self.import_repo.update_row(
            row,
            status="warning",
            errors=issues,
            review_required=True,
        )

        summary = dict(session.summary_json or {})
        summary["ready_rows"] = max(0, int(summary.get("ready_rows", 0)) - 1)
        summary["warning_rows"] = int(summary.get("warning_rows", 0)) + 1
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)

        return {
            "id": row.id,
            "session_id": session.id,
            "row_index": row.row_index,
            "status": row.status,
            "confidence": float(getattr(row, "confidence_score", 0.0) or 0.0),
            "confidence_label": self._confidence_label(getattr(row, "confidence_score", 0.0) or 0.0),
            "issues": getattr(row, "errors", None) or [],
            "unresolved_fields": [],
            "error_message": row.error_message,
            "review_required": bool(getattr(row, "review_required", False)),
            "raw_data": getattr(row, "raw_data", None) or (row.raw_data_json or {}),
            "normalized_data": getattr(row, "normalized_data", None) or (row.normalized_data_json or {}),
        }


    def list_review_queue(self, *, user_id: int) -> dict[str, Any]:
        queue_rows = self.import_repo.list_review_queue(user_id=user_id)
        items: list[dict[str, Any]] = []

        for session, row in queue_rows:
            issues = getattr(row, "errors", None)
            if issues is None:
                message = row.error_message or ""
                issues = [item.strip() for item in message.splitlines() if item.strip()]

            items.append(
                {
                    "session_id": session.id,
                    "session_status": session.status,
                    "filename": session.filename,
                    "source_type": session.source_type,
                    "row_id": row.id,
                    "row_index": row.row_index,
                    "status": row.status,
                    "error_message": row.error_message,
                    "issues": issues or [],
                    "raw_data": getattr(row, "raw_data", None) or (row.raw_data_json or {}),
                    "normalized_data": getattr(row, "normalized_data", None) or (row.normalized_data_json or {}),
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )

        return {
            "items": items,
            "total": len(items),
        }

    def list_parked_queue(self, *, user_id: int) -> dict[str, Any]:
        """Global list of parked rows across all the user's sessions.

        Parked rows are rows the user explicitly deferred — they don't get
        committed into Transactions and therefore don't enter analytics.
        """
        parked_rows = self.import_repo.list_parked_queue(user_id=user_id)
        items: list[dict[str, Any]] = []
        for session, row in parked_rows:
            items.append(
                {
                    "session_id": session.id,
                    "session_status": session.status,
                    "filename": session.filename,
                    "source_type": session.source_type,
                    "row_id": row.id,
                    "row_index": row.row_index,
                    "status": row.status,
                    "raw_data": getattr(row, "raw_data", None) or (row.raw_data_json or {}),
                    "normalized_data": getattr(row, "normalized_data", None) or (row.normalized_data_json or {}),
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )
        return {"items": items, "total": len(items)}

    def get_moderation_status(self, *, user_id: int, session_id: int) -> dict[str, Any]:
        """Return the LLM moderation status for a session.

        Shape (always):
          {
            "session_id": int,
            "status": "pending" | "running" | "ready" | "failed" | "skipped",
            "total_clusters": int,
            "processed_clusters": int,
            "started_at": iso | null,
            "finished_at": iso | null,
            "error": str | null,
            "clusters": [  # per-cluster hypotheses (may be empty if not started)
                {
                    "cluster_fingerprint": str,
                    "status": "ready" | "skipped",
                    "cluster_row_ids": list[int],
                    "hypothesis": dict | null,
                },
                ...
            ],
          }
        """
        session = self.get_session(user_id=user_id, session_id=session_id)
        summary = session.summary_json or {}
        moderation = dict(summary.get("moderation") or {})

        # "not_started" means the user has never clicked "Запустить модератор"
        # for this session. The frontend uses this to decide whether to show
        # the start button. "pending" is reserved for sessions where the API
        # accepted the kick-off but Celery hasn't picked it up yet.
        status_value = moderation.get("status") or "not_started"

        # Join LLM hypotheses (stored on anchor rows) with cluster metadata
        # rebuilt on the fly. Rebuilding is cheap (one grouping pass over row
        # JSON) and gives us the Phase-7 trust fields — trust_zone,
        # identifier_match, rule_confirms/rejections, auto_trust — which are
        # not persisted in normalized_data.moderation.
        from app.services.import_cluster_service import ImportClusterService

        rows = self.import_repo.get_rows(session_id=session.id)
        live_clusters = ImportClusterService(self.db).build_clusters(session)
        cluster_meta_by_fp = {c.fingerprint: c.to_dict() for c in live_clusters}

        clusters: list[dict[str, Any]] = []
        auto_trust_rows = 0
        attention_rows = 0
        for row in rows:
            normalized = getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
            mod_block = normalized.get("moderation")
            if not mod_block:
                continue
            fp = mod_block.get("cluster_fingerprint")
            cluster_entry = {
                "cluster_fingerprint": fp,
                "status": mod_block.get("status"),
                "cluster_row_ids": mod_block.get("cluster_row_ids") or [],
                "hypothesis": mod_block.get("hypothesis"),
            }
            live_meta = cluster_meta_by_fp.get(fp) if fp else None
            if live_meta is not None:
                cluster_entry.update(
                    {
                        "trust_zone": live_meta.get("trust_zone"),
                        "auto_trust": live_meta.get("auto_trust", False),
                        "confidence": live_meta.get("confidence"),
                        "identifier_match": live_meta.get("identifier_match"),
                        "identifier_key": live_meta.get("identifier_key"),
                        "identifier_value": live_meta.get("identifier_value"),
                        "rule_source": live_meta.get("rule_source"),
                        "rule_confirms": live_meta.get("rule_confirms"),
                        "rule_rejections": live_meta.get("rule_rejections"),
                        "candidate_category_id": live_meta.get("candidate_category_id"),
                        "count": live_meta.get("count"),
                        "total_amount": live_meta.get("total_amount"),
                        "skeleton": live_meta.get("skeleton"),
                        "bank_code": live_meta.get("bank_code"),
                        # Layer 1: account-context hints
                        "account_context_operation_type": live_meta.get("account_context_operation_type"),
                        "account_context_category_id": live_meta.get("account_context_category_id"),
                        "account_context_label": live_meta.get("account_context_label"),
                        # Layer 2: bank-mechanics hints
                        "bank_mechanics_operation_type": live_meta.get("bank_mechanics_operation_type"),
                        "bank_mechanics_category_id": live_meta.get("bank_mechanics_category_id"),
                        "bank_mechanics_label": live_meta.get("bank_mechanics_label"),
                        "bank_mechanics_cross_session_warning": live_meta.get("bank_mechanics_cross_session_warning"),
                        # Layer 3: global cross-user pattern
                        "global_pattern_category_id": live_meta.get("global_pattern_category_id"),
                        "global_pattern_category_name": live_meta.get("global_pattern_category_name"),
                        "global_pattern_user_count": live_meta.get("global_pattern_user_count"),
                        "global_pattern_total_confirms": live_meta.get("global_pattern_total_confirms"),
                    }
                )
                row_count = len(cluster_entry["cluster_row_ids"])
                if live_meta.get("auto_trust"):
                    auto_trust_rows += row_count
                else:
                    attention_rows += row_count
            else:
                attention_rows += len(cluster_entry["cluster_row_ids"])
            clusters.append(cluster_entry)

        return {
            "session_id": session.id,
            "status": status_value,
            "total_clusters": moderation.get("total_clusters", 0),
            "processed_clusters": moderation.get("processed_clusters", 0),
            "started_at": moderation.get("started_at"),
            "finished_at": moderation.get("finished_at"),
            "error": moderation.get("error"),
            "clusters": clusters,
            "auto_trust_rows": auto_trust_rows,
            "attention_rows": attention_rows,
        }

    def start_moderation(self, *, user_id: int, session_id: int) -> dict[str, Any]:
        """Kick off an async LLM moderation run for a session.

        The actual work is a Celery task; this method just (1) marks the
        session as "pending" so the UI can start polling, and (2) enqueues
        the task. It returns immediately.
        """
        session = self.get_session(user_id=user_id, session_id=session_id)
        summary = dict(session.summary_json or {})
        moderation = dict(summary.get("moderation") or {})
        moderation.update(
            {
                "status": "pending",
                "total_clusters": moderation.get("total_clusters", 0),
                "processed_clusters": 0,
                "started_at": None,
                "finished_at": None,
                "error": None,
            }
        )
        summary["moderation"] = moderation
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()

        # Import lazily to avoid circular imports at module load.
        from app.jobs.moderate_import_session import moderate_import_session

        moderate_import_session.delay(session.id)
        return {"session_id": session.id, "status": "pending"}

    def park_row(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        """Mark a row as parked — deferred from this import, kept in a global queue."""
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Импортированную строку нельзя отложить.")

        row = self.import_repo.update_row(row, status="parked", review_required=False)
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)
        return {"session_id": session.id, "row_id": row.id, "status": row.status, "summary": summary}

    def unpark_row(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        """Restore a parked row to warning status so it can be reviewed and committed again."""
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row_status != "parked":
            raise ImportValidationError("Только отложенные строки можно вернуть в очередь.")

        row = self.import_repo.update_row(row, status="warning", review_required=True)
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)
        return {"session_id": session.id, "row_id": row.id, "status": row.status, "summary": summary}


    def exclude_row(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        """Mark a row as skipped — excluded from import deliberately by the user."""
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")
        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Импортированную строку нельзя исключить.")
        row = self.import_repo.update_row(row, status="skipped", review_required=False)
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)
        return {"session_id": session.id, "row_id": row.id, "status": row.status, "summary": summary}

    def detach_row_from_cluster(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        """Detach a row from any bulk cluster so it lands in the attention bucket.

        Sets `normalized_data.detached_from_cluster = True`. `build_bulk_clusters`
        skips such rows during cluster assembly, so the row falls into the
        inline attention list where the user can categorize it individually.
        Status goes to `warning` (+ clears auto-inherited category/counterparty)
        so the row is treated as "needs decision" rather than "ready to import".
        """
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")
        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Импортированную строку нельзя открепить.")
        nd = dict(row.normalized_data_json or {})
        nd["detached_from_cluster"] = True
        # Cluster-inherited fields (category + counterparty) belong to the
        # cluster's context — once the row is standalone the user must
        # re-decide. Drop them so the attention UI shows a blank slate
        # instead of silently committing the auto-inherited values.
        nd["category_id"] = None
        nd["counterparty_id"] = None
        row = self.import_repo.update_row(
            row, normalized_data=nd, status="warning", review_required=True,
        )
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)
        return {"session_id": session.id, "row_id": row.id, "status": row.status, "summary": summary}

    def unexclude_row(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        """Restore a skipped row to warning status so it can be reviewed again."""
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")
        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row_status != "skipped":
            raise ImportValidationError("Только исключённые строки можно вернуть.")
        row = self.import_repo.update_row(row, status="warning", review_required=True)
        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)
        return {"session_id": session.id, "row_id": row.id, "status": row.status, "summary": summary}

    def update_row(self, *, user_id: int, row_id: int, payload: ImportRowUpdateRequest) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("РЎС‚СЂРѕРєР° РёРјРїРѕСЂС‚Р° РЅРµ РЅР°Р№РґРµРЅР°.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("РРјРїРѕСЂС‚РёСЂРѕРІР°РЅРЅСѓСЋ СЃС‚СЂРѕРєСѓ РЅРµР»СЊР·СЏ РёР·РјРµРЅРёС‚СЊ.")

        normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))

        # Capture rule metadata before payload overwrites category_id.
        _prior_rule_id = normalized.get("applied_rule_id")
        _prior_rule_cat = normalized.get("applied_rule_category_id")

        for field in ("account_id", "target_account_id", "credit_account_id", "category_id", "counterparty_id", "debt_partner_id", "amount", "type", "operation_type", "debt_direction", "description", "currency", "credit_principal_amount", "credit_interest_amount"):
            value = getattr(payload, field)
            if value is not None:
                normalized[field] = value

        # §10.3: rejections are counted ONLY on commit, not on intermediate
        # user edits ("поменял → вернул как было" must not leave a rejection
        # trace). Keep applied_rule_id + applied_rule_category_id intact here;
        # the commit path compares them against the final category_id and
        # routes to Case A/B (match → confirm) or Case C (diff → reject old +
        # create new). This reflects §10.2 Cases A/B/C.

        if payload.split_items is not None:
            normalized["split_items"] = [
                {
                    "operation_type": (item.operation_type or "regular"),
                    "category_id": item.category_id,
                    "target_account_id": item.target_account_id,
                    "debt_direction": item.debt_direction,
                    "counterparty_id": item.counterparty_id,
                    "debt_partner_id": item.debt_partner_id,
                    "amount": str(item.amount),
                    "description": item.description,
                }
                for item in payload.split_items
            ]

        if payload.transaction_date is not None:
            normalized["transaction_date"] = payload.transaction_date.isoformat()
            normalized["date"] = payload.transaction_date.isoformat()

        action = (payload.action or "").strip().lower()
        issues = [item for item in (getattr(row, "errors", None) or []) if item and item != "РСЃРєР»СЋС‡РµРЅРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»РµРј."]
        status = row_status if row_status not in {"committed", "duplicate"} else row_status
        allow_ready_status = action == "confirm"

        if action == "exclude":
            status = "skipped"
            issues = list(dict.fromkeys([*issues, "РСЃРєР»СЋС‡РµРЅРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»РµРј."]))
        else:
            if action == "restore" and row_status == "skipped":
                status = "warning"
            elif action == "confirm":
                # §5.4 / §10.2 (v1.1): individual confirm is a full-touch
                # signal — the user read THIS row and vouched for it. Stamp
                # user_confirmed_at so commit can: (a) let the row through,
                # (b) apply Case A weight 1.0 (not 0.5). Preserved even when
                # the status resolves to `ready` because bulk-ack paths
                # distinguish by which flag is present.
                #
                # v1.8: stamp the timestamp regardless of prior status. An
                # auto-trust row also lands in `ready`, but on the next
                # /moderation-status fetch its cluster.auto_trust may flip
                # to false (cluster recompute lowered confidence) and §1.2
                # honesty gate kicks the row back into attention. The user
                # already explicitly confirmed it once — without the stamp
                # the UI keeps demanding re-confirmation after every refresh.
                from datetime import datetime as _dt, timezone as _tz
                normalized["user_confirmed_at"] = _dt.now(_tz.utc).isoformat()
                # Individual confirm supersedes any lingering cluster-ack
                # from a prior bulk pass on the same row.
                normalized.pop("cluster_bulk_acked_at", None)
                status = "ready"
                # If auto-detected as transfer but has no target, revert to regular
                # so the user can confirm without a validation blocker.
                if (
                    str(normalized.get("operation_type") or "") == "transfer"
                    and not normalized.get("target_account_id")
                ):
                    normalized["operation_type"] = "regular"
                    normalized.pop("transfer_match", None)
            elif row_status in {"ready", "warning"}:
                status = "warning"

            status, issues = self._validate_manual_row(
                normalized=normalized,
                current_status=status,
                issues=issues,
                allow_ready_status=allow_ready_status,
            )

        row = self.import_repo.update_row(
            row,
            normalized_data=normalized,
            status=status,
            errors=issues,
            review_required=status in {"warning", "error"},
        )

        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)

        return {
            "session_id": session.id,
            "row": self._serialize_preview_row(row),
            "summary": summary,
        }

    @staticmethod
    def _gate_transfer_integrity(
        *,
        normalized: dict[str, Any],
        current_status: str,
        issues: list[str],
        final: bool = False,
    ) -> tuple[str, list[str]]:
        """§12.1 / §5.2 v1.1 trigger 6 — transfer with only one known account
        is forbidden in a final state.

        Two-stage:
          * `final=False` (preview, before the async transfer-matcher runs):
            escalate to `warning`. The cross-session matcher
            (`schedule_transfer_match`, debounced ~3s) only sees rows in
            ready/warning, so we MUST stay out of `error` long enough for it
            to attempt pairing. Premature `error` blocked the matcher and
            broke Tinkoff intra-bank transfers (orphan + missed-pair regression).
          * `final=True` (post-matcher cleanup, individual edits, commit
            guard): escalate to `error`. After the matcher's last attempt,
            a still-orphan transfer is a real §12.1 violation.

        Either way, do NOT silently demote `operation_type` to `regular` —
        that hid the problem in the silent-demotion era and let half-transfers
        commit as regular expenses.

        Pure function: no DB access, no side effects beyond the returned
        `(status, issues)` tuple. Unit-tested directly.
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
        # phantom pair against the same account. Surfaces a real bug observed
        # in session 229: the normalizer rewrote `account_id` from the
        # session's account to the one mentioned in the description, so both
        # sides ended up on acc=22. Treat it as a missing target — the user
        # must pick a real counter-account.
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

        # §5.2 / §8.3: terminal states stick. `duplicate` is terminal-ish;
        # `error` only deepens (never softens to warning).
        if current_status in ("duplicate", "error"):
            return current_status, next_issues

        target_status = "error" if final else "warning"
        # Status priority: ready < warning < error. Don't downgrade.
        priority = {"ready": 0, "skipped": 0, "warning": 1, "error": 2}
        if priority.get(target_status, 0) <= priority.get(current_status, 0):
            return current_status, next_issues
        return target_status, next_issues

    def _validate_manual_row(self, *, normalized: dict[str, Any], current_status: str, issues: list[str], allow_ready_status: bool = True) -> tuple[str, list[str]]:
        status = current_status
        local_issues = [item for item in issues if item]

        # §5.2 (v1.1): status priority is ready < warning < error. Once a
        # data-integrity error fires, a subsequent quality warning must NOT
        # downgrade it. This helper enforces monotonic escalation — call it
        # instead of bare `status = "warning"` / `status = "error"`.
        _priority = {"ready": 0, "skipped": 0, "warning": 1, "error": 2}
        def _escalate(new: str) -> str:
            nonlocal status
            if _priority.get(new, 0) > _priority.get(status, 0):
                status = new
            return status

        if status == "skipped":
            return status, list(dict.fromkeys(local_issues))

        blocking_messages = {
            "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚.",
            "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РїРѕСЃС‚СѓРїР»РµРЅРёСЏ.",
            "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РѕС‚РїСЂР°РІРёС‚РµР»СЏ.",
            "РќРµ РІС‹Р±СЂР°РЅ РєСЂРµРґРёС‚РЅС‹Р№ СЃС‡С‘С‚.",
            "РќРµ РІС‹Р±СЂР°РЅР° РєР°С‚РµРіРѕСЂРёСЏ.",
            "Р Р°Р·Р±РёРІРєР° Р·Р°РїРѕР»РЅРµРЅР° РЅРµРєРѕСЂСЂРµРєС‚РЅРѕ.",
            "РЎСѓРјРјР° СЂР°Р·Р±РёРІРєРё РґРѕР»Р¶РЅР° СЃРѕРІРїР°РґР°С‚СЊ СЃ СЃСѓРјРјРѕР№ С‚СЂР°РЅР·Р°РєС†РёРё.",
            "Р’ СЂР°Р·Р±РёРІРєРµ РєР°Р¶РґР°СЏ С‡Р°СЃС‚СЊ РґРѕР»Р¶РЅР° Р±С‹С‚СЊ Р±РѕР»СЊС€Рµ РЅСѓР»СЏ.",
            "Р’ СЂР°Р·Р±РёРІРєРµ РґР»СЏ РєР°Р¶РґРѕР№ С‡Р°СЃС‚Рё РЅСѓР¶РЅР° РєР°С‚РµРіРѕСЂРёСЏ.",
            "Р”Р»СЏ РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РѕСЃРЅРѕРІРЅРѕР№ РґРѕР»Рі.",
            "Р”Р»СЏ РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РїСЂРѕС†РµРЅС‚С‹.",
            "РЎСѓРјРјР° РѕСЃРЅРѕРІРЅРѕРіРѕ РґРѕР»РіР° Рё РїСЂРѕС†РµРЅС‚РѕРІ РґРѕР»Р¶РЅР° СЃРѕРІРїР°РґР°С‚СЊ СЃ РѕР±С‰РµР№ СЃСѓРјРјРѕР№ РїР»Р°С‚РµР¶Р°.",
            "РћСЃРЅРѕРІРЅРѕР№ РґРѕР»Рі Рё РїСЂРѕС†РµРЅС‚С‹ РЅРµ РјРѕРіСѓС‚ Р±С‹С‚СЊ РѕС‚СЂРёС†Р°С‚РµР»СЊРЅС‹РјРё.",
            "РџСѓСЃС‚РѕРµ РѕРїРёСЃР°РЅРёРµ РѕРїРµСЂР°С†РёРё.",
            "РќРµ СѓРєР°Р·Р°РЅР° РґР°С‚Р° РѕРїРµСЂР°С†РёРё.",
            "РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ СЃСѓРјРјР°.",
            "РЎС‡С‘С‚ СЃРїРёСЃР°РЅРёСЏ Рё СЃС‡С‘С‚ РїРѕСЃС‚СѓРїР»РµРЅРёСЏ РЅРµ РґРѕР»Р¶РЅС‹ СЃРѕРІРїР°РґР°С‚СЊ.",
        }
        local_issues = [item for item in local_issues if item not in blocking_messages]

        account_id = normalized.get("account_id")
        operation_type = normalized.get("operation_type") or "regular"
        amount = normalized.get("amount")

        # §12.3: operation_type="credit_payment" is forbidden as a real value,
        # but the moderator UI may submit it as a meta-signal ("user tapped
        # the split-form button"). Fold it into (operation_type=transfer +
        # requires_credit_split=True) so the stored normalized_data never
        # carries the forbidden value. The validation and commit branches
        # below key off requires_credit_split, not operation_type.
        if operation_type == "credit_payment":
            normalized["requires_credit_split"] = True
            normalized["operation_type"] = "transfer"
            operation_type = "transfer"

        if account_id in (None, "", 0):
            # §5.2 / §12.1 (v1.1): a row without a known account is a data-
            # integrity error, not a quality warning. No Transaction can be
            # created without account_id, so bulk-ack must never push it
            # through. User has to pick the account, exclude, or park.
            local_issues.append("РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚.")
            status = "error"

        amount_decimal = None
        try:
            if amount not in (None, ""):
                amount_decimal = self._to_decimal(amount)
        except (ValueError, TypeError, InvalidOperation):
            local_issues.append("РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ СЃСѓРјРјР°.")
            status = "error"

        if operation_type == "transfer" and not normalized.get("requires_credit_split"):
            target_account_id = normalized.get("target_account_id")
            tx_type = str(normalized.get("type") or "expense")
            normalized["credit_account_id"] = None
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            if target_account_id in (None, "", 0):
                # §12.1 / §5.2 (v1.1): transfer with only one known account is
                # forbidden — promoted from warning to error so bulk-ack can't
                # sneak it through. User must set the counter-account manually,
                # park the row, or exclude it.
                # For income transfers, target = source account; for expense, target = destination.
                missing_msg = "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РѕС‚РїСЂР°РІРёС‚РµР»СЏ." if tx_type == "income" else "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РїРѕСЃС‚СѓРїР»РµРЅРёСЏ."
                local_issues.append(missing_msg)
                status = "error"
            elif str(target_account_id) == str(account_id):
                local_issues.append("РЎС‡С‘С‚ СЃРїРёСЃР°РЅРёСЏ Рё СЃС‡С‘С‚ РїРѕСЃС‚СѓРїР»РµРЅРёСЏ РЅРµ РґРѕР»Р¶РЅС‹ СЃРѕРІРїР°РґР°С‚СЊ.")
                status = "error"
            normalized["category_id"] = None
            normalized["split_items"] = []
        elif operation_type == "credit_disbursement":
            normalized["target_account_id"] = None
            normalized["credit_account_id"] = None
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            normalized["category_id"] = None
            normalized["split_items"] = []
        elif operation_type == "credit_early_repayment":
            # Досрочное погашение: TransactionService требует target_account_id
            # = кредитный счёт (см. transaction_service._resolve_target_account).
            # UI может прислать кредитный счёт либо как target_account_id, либо
            # как credit_account_id — нормализуем в target_account_id, чтобы
            # не уронить коммит на else-ветке (которая раньше затирала поле).
            credit_account_id = normalized.get("target_account_id") or normalized.get("credit_account_id")
            normalized["target_account_id"] = credit_account_id
            normalized["credit_account_id"] = credit_account_id
            normalized["category_id"] = None
            normalized["split_items"] = []
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            if credit_account_id in (None, "", 0):
                # Mojibake form matches the entry in blocking_messages set above
                # so the post-validation pass at the end of this function picks
                # this up as a real blocker (and won't reset status to ready).
                local_issues.append("РќРµ РІС‹Р±СЂР°РЅ РєСЂРµРґРёС‚РЅС‹Р№ СЃС‡С‘С‚.")
                _escalate("warning")
        elif operation_type == "transfer" and normalized.get("requires_credit_split"):
            # §9.3 split: transfer to a loan account that must be committed as
            # (interest expense + principal transfer). Validates the split
            # amounts here; the actual two-transaction creation happens at
            # commit time in commit_import.
            credit_account_id = normalized.get("credit_account_id") or normalized.get("target_account_id")
            normalized["category_id"] = None
            normalized["split_items"] = []
            normalized["target_account_id"] = credit_account_id
            normalized["credit_account_id"] = credit_account_id
            if credit_account_id in (None, "", 0):
                local_issues.append("РќРµ РІС‹Р±СЂР°РЅ РєСЂРµРґРёС‚РЅС‹Р№ СЃС‡С‘С‚.")
                _escalate("warning")

            principal_raw = normalized.get("credit_principal_amount")
            interest_raw = normalized.get("credit_interest_amount")
            principal_amount = None
            interest_amount = None

            if principal_raw in (None, ""):
                local_issues.append("Р”Р»СЏ РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РѕСЃРЅРѕРІРЅРѕР№ РґРѕР»Рі.")
                _escalate("warning")
            else:
                try:
                    principal_amount = self._to_decimal(principal_raw)
                except (ValueError, TypeError, InvalidOperation):
                    local_issues.append("РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ СЃСѓРјРјР°.")
                    _escalate("error")

            if interest_raw in (None, ""):
                local_issues.append("Р”Р»СЏ РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РїСЂРѕС†РµРЅС‚С‹.")
                _escalate("warning")
            else:
                try:
                    interest_amount = self._to_decimal(interest_raw)
                except (ValueError, TypeError, InvalidOperation):
                    local_issues.append("РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ СЃСѓРјРјР°.")
                    status = "error"

            if principal_amount is not None and interest_amount is not None:
                if principal_amount < 0 or interest_amount < 0:
                    local_issues.append("РћСЃРЅРѕРІРЅРѕР№ РґРѕР»Рі Рё РїСЂРѕС†РµРЅС‚С‹ РЅРµ РјРѕРіСѓС‚ Р±С‹С‚СЊ РѕС‚СЂРёС†Р°С‚РµР»СЊРЅС‹РјРё.")
                    status = "error"
                elif amount_decimal is not None and principal_amount + interest_amount != amount_decimal:
                    # Bank statements sometimes round principal/interest split by a few
                    # kopecks. If the mismatch is small (<= 1 RUB), snap interest to match
                    # the total. Larger mismatches are real user errors.
                    diff = amount_decimal - (principal_amount + interest_amount)
                    if abs(diff) <= Decimal("1.00"):
                        interest_amount = interest_amount + diff
                    else:
                        local_issues.append("Sum of principal + interest does not match total (off by more than 1 RUB)")
                        status = "error"
                normalized["credit_principal_amount"] = str(principal_amount)
                normalized["credit_interest_amount"] = str(interest_amount)
        elif operation_type == "regular":
            split_items = normalized.get("split_items") or []
            normalized["target_account_id"] = None
            if split_items:
                # Split parts can each have their own operation_type — one bank
                # debit may economically be a regular expense + a debt slice +
                # a transfer slice, etc. Validate each part by its own type
                # instead of forcing them all to be regular.
                # §12.3: credit_payment is NOT a valid operation_type. A loan
                # payment split inside split_items would create a Transaction
                # with a forbidden type — catch it here at validation time
                # instead of letting it blow up at the ORM enum check.
                ALLOWED_PART_TYPES = {
                    "regular", "transfer", "refund", "debt",
                    "investment_buy", "investment_sell",
                    "credit_disbursement", "credit_early_repayment",
                }
                ALLOWED_DEBT_DIRS = {"borrowed", "lent", "repaid", "collected"}
                valid_split = True
                split_total = Decimal("0")
                cleaned_split_items: list[dict[str, Any]] = []
                for item in split_items:
                    if not isinstance(item, dict):
                        valid_split = False
                        local_issues.append("Разбивка заполнена некорректно.")
                        break

                    part_op = str(item.get("operation_type") or "regular").lower()
                    if part_op not in ALLOWED_PART_TYPES:
                        valid_split = False
                        local_issues.append(f"Неизвестный тип операции в части разбивки: {part_op}.")
                        break

                    raw_amount = item.get("amount")
                    description = item.get("description")
                    try:
                        split_amount = self._to_decimal(raw_amount)
                    except (ValueError, TypeError, InvalidOperation):
                        valid_split = False
                        local_issues.append("Разбивка заполнена некорректно.")
                        break
                    if split_amount <= 0:
                        valid_split = False
                        local_issues.append("В разбивке каждая часть должна быть больше нуля.")
                        break

                    category_id = item.get("category_id")
                    target_account_id = item.get("target_account_id")
                    debt_direction = item.get("debt_direction")
                    counterparty_id = item.get("counterparty_id")
                    debt_partner_id = item.get("debt_partner_id")

                    # Per-type required fields. Refuse silently-incomplete
                    # parts up front instead of letting commit_import blow up.
                    if part_op in ("regular", "refund"):
                        if category_id in (None, "", 0):
                            valid_split = False
                            local_issues.append("В разбивке для каждой части нужна категория.")
                            break
                    if part_op == "debt":
                        if not debt_direction or str(debt_direction).lower() not in ALLOWED_DEBT_DIRS:
                            valid_split = False
                            local_issues.append("В части-долге укажи направление: занял/одолжил/возврат/получил.")
                            break
                        if debt_partner_id in (None, "", 0):
                            valid_split = False
                            local_issues.append("В части-долге укажи дебитора / кредитора.")
                            break
                    if part_op == "transfer":
                        if target_account_id in (None, "", 0):
                            valid_split = False
                            local_issues.append("В части-переводе укажи счёт назначения.")
                            break

                    cleaned_split_items.append({
                        "operation_type": part_op,
                        "category_id": int(category_id) if category_id not in (None, "", 0) else None,
                        "target_account_id": int(target_account_id) if target_account_id not in (None, "", 0) else None,
                        "debt_direction": str(debt_direction).lower() if debt_direction else None,
                        "counterparty_id": int(counterparty_id) if counterparty_id not in (None, "", 0) else None,
                        "debt_partner_id": int(debt_partner_id) if debt_partner_id not in (None, "", 0) else None,
                        "amount": str(split_amount),
                        "description": description,
                    })
                    split_total += split_amount

                if valid_split and amount_decimal is not None and split_total != amount_decimal:
                    valid_split = False
                    local_issues.append("Сумма разбивки должна совпадать с суммой транзакции.")

                if valid_split and len(cleaned_split_items) >= 2:
                    normalized["split_items"] = cleaned_split_items
                    normalized["category_id"] = None
                else:
                    _escalate("warning")
            else:
                normalized["split_items"] = []
                if normalized.get("category_id") in (None, "", 0):
                    local_issues.append("Не выбрана категория.")
                    _escalate("warning")
        elif operation_type == "refund":
            normalized["target_account_id"] = None
            normalized["split_items"] = []
            if normalized.get("category_id") in (None, "", 0):
                local_issues.append("РќРµ РІС‹Р±СЂР°РЅР° РєР°С‚РµРіРѕСЂРёСЏ.")
                _escalate("warning")
        else:
            normalized["target_account_id"] = None
            normalized["category_id"] = None
            normalized["split_items"] = []

        if not normalized.get("description"):
            local_issues.append("РџСѓСЃС‚РѕРµ РѕРїРёСЃР°РЅРёРµ РѕРїРµСЂР°С†РёРё.")
            _escalate("warning")

        if not normalized.get("transaction_date") and not normalized.get("date"):
            local_issues.append("РќРµ СѓРєР°Р·Р°РЅР° РґР°С‚Р° РѕРїРµСЂР°С†РёРё.")
            status = "error"

        unique_issues = list(dict.fromkeys(local_issues))

        # §5.2 (v1.1): error is sticky. Once any integrity check escalated to
        # error above, do NOT downgrade it to ready/warning at the resolution
        # step. The spec's status priority is ready < warning < error.
        if status != "duplicate" and status != "error":
            unresolved = [item for item in unique_issues if item in blocking_messages]
            if unresolved:
                status = status if status in {"warning", "error", "skipped"} else "warning"
            elif allow_ready_status:
                status = "ready"
            elif status not in {"error", "skipped"}:
                status = "warning"

        return status, unique_issues

    def _build_summary_from_rows(self, rows: list[ImportRow]) -> dict[str, int]:
        summary = {
            "total_rows": len(rows),
            "ready_rows": 0,
            "warning_rows": 0,
            "error_rows": 0,
            "duplicate_rows": 0,
            "skipped_rows": 0,
            "parked_rows": 0,
        }
        for row in rows:
            status = str(row.status or "").strip().lower()
            if status == "ready":
                summary["ready_rows"] += 1
            elif status == "warning":
                summary["warning_rows"] += 1
            elif status == "duplicate":
                summary["duplicate_rows"] += 1
                summary["skipped_rows"] += 1
            elif status == "skipped":
                summary["skipped_rows"] += 1
            elif status == "error":
                summary["error_rows"] += 1
            elif status == "parked":
                summary["parked_rows"] += 1
                summary["skipped_rows"] += 1
        return summary

    def _apply_refund_matches(self, *, session_id: int) -> None:
        """Run RefundMatcherService over the session's rows and persist pairs.

        For each matched pair, both sides get `normalized_data["refund_match"]`
        with: partner_row_id, partner_date, partner_description, amount,
        confidence, reasons. We do NOT change the row's status or
        operation_type — that decision stays with the user via the moderator UI.
        Rows that already have an `operation_type='transfer'` annotation (from
        the transfer matcher) are excluded — refund and transfer are mutually
        exclusive labels for the same row.
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

    def _apply_refund_cluster_overrides(self, *, session: ImportSession) -> None:
        """Stamp refund metadata onto every row of a refund cluster.

        For each cluster where `is_refund=True` and a counterparty/category
        could be inherited from the user's purchase history at the same
        brand (see `ImportClusterService._resolve_refund_counterparty`),
        update every row in the cluster:

          - `operation_type = 'refund'` (overrides regular/transfer guesses)
          - `type = 'income'` (refund direction is always income on the user's
            account — money returned)
          - `category_id` = dominant category used for past purchases at this
            counterparty (so analytics can subtract this income from that
            category's expense total — the compensator model)
          - `counterparty_id` = the purchase-side counterparty, so the UI
            renders the refund under the same name as the purchases

        Rows where the user already set a manual `user_label` or a
        `counterparty_id` that differs from the inherited one are left
        untouched — manual overrides win over auto-inheritance.

        If the cluster has `is_refund=True` but no category inherited
        (new merchant, or no categorized purchase history yet), we still
        stamp `operation_type='refund'` and `type='income'` but leave
        category empty — the row stays in the attention bucket for the
        user to pick a category manually, but at least it won't end up
        classified as plain income in the ledger.
        """
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
                # Don't stomp on explicit user edits. user_label is set when
                # the user manually assigns a category in the moderator UI;
                # preserving it means a post-edit rebuild of preview does
                # not wipe their choice.
                has_user_label = bool(nd.get("user_label"))
                nd["operation_type"] = "refund"
                nd["type"] = "income"
                nd["direction"] = "income"
                if cluster.candidate_category_id is not None and not has_user_label:
                    nd["category_id"] = int(cluster.candidate_category_id)
                if cluster.refund_resolved_counterparty_id is not None:
                    existing_cp = nd.get("counterparty_id")
                    # Only overwrite counterparty when none is set; a manually
                    # assigned counterparty from the user takes priority.
                    if existing_cp in (None, "", 0):
                        nd["counterparty_id"] = int(cluster.refund_resolved_counterparty_id)
                self.import_repo.update_row(row, normalized_data=nd)

    def _recalculate_summary(self, session_id: int) -> dict[str, Any]:
        # Merge fresh row counts into the existing summary so non-counter blocks
        # (most importantly "moderation" — its absence flips the UI back to
        # "not started" and hides the attention bucket on the next status poll)
        # survive single-row mutations like park / exclude / update.
        rows = self.import_repo.get_rows(session_id=session_id)
        counts = self._build_summary_from_rows(rows)
        session = (
            self.db.query(ImportSession).filter(ImportSession.id == session_id).first()
        )
        existing = dict((session.summary_json if session else None) or {})
        existing.update(counts)
        return existing

    def _serialize_preview_row(self, row: ImportRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "row_index": row.row_index,
            "status": row.status,
            "confidence": float(getattr(row, "confidence_score", 0.0) or 0.0),
            "confidence_label": self._confidence_label(getattr(row, "confidence_score", 0.0) or 0.0),
            "issues": getattr(row, "errors", None) or [],
            "unresolved_fields": [],
            "error_message": row.error_message,
            "review_required": bool(getattr(row, "review_required", False)),
            "raw_data": getattr(row, "raw_data", None) or (row.raw_data_json or {}),
            "normalized_data": getattr(row, "normalized_data", None) or (row.normalized_data_json or {}),
        }


    def get_existing_preview(self, *, user_id: int, session_id: int) -> dict[str, Any]:
        session = self.get_session(user_id=user_id, session_id=session_id)
        rows = self.import_repo.list_rows(session_id=session.id)
        summary = session.summary_json or self._build_summary_from_rows(rows)
        detection = session.mapping_json or (session.parse_settings or {}).get("detection", {})
        return {
            "session_id": session.id,
            "status": session.status,
            "summary": summary,
            "detection": detection,
            "rows": [self._serialize_preview_row(row) for row in rows],
        }

    def build_preview(self, *, user_id: int, session_id: int, payload: ImportMappingRequest) -> dict[str, Any]:
        session = self.get_session(user_id=user_id, session_id=session_id)
        # Serialize concurrent build_preview calls for the same session — prevents
        # the race where two parallel requests each rebuild rows and both sets survive.
        from sqlalchemy import text as _sa_text
        self.db.execute(
            _sa_text("SELECT id FROM import_sessions WHERE id = :sid FOR UPDATE"),
            {"sid": session.id},
        )
        account = self.account_repo.get_by_id_and_user(payload.account_id, user_id)
        if account is None:
            raise ImportValidationError("Р’С‹Р±СЂР°РЅРЅС‹Р№ СЃС‡С‘С‚ РЅРµ РЅР°Р№РґРµРЅ.")

        tables = self._load_tables_from_session(session)
        if not tables:
            raise ImportValidationError("РќРµ СѓРґР°Р»РѕСЃСЊ РІРѕСЃСЃС‚Р°РЅРѕРІРёС‚СЊ РґР°РЅРЅС‹Рµ СЃРµСЃСЃРёРё РёРјРїРѕСЂС‚Р°.")

        current_mapping = session.mapping_json or {}
        table_name = payload.table_name or current_mapping.get("selected_table") or tables[0].name
        table = next((item for item in tables if item.name == table_name), None)
        if table is None:
            raise ImportValidationError("Р’С‹Р±СЂР°РЅРЅР°СЏ С‚Р°Р±Р»РёС†Р° РЅРµ РЅР°Р№РґРµРЅР° РІ РёСЃС‚РѕС‡РЅРёРєРµ.")
        if not table.rows:
            raise ImportValidationError("Р’ РІС‹Р±СЂР°РЅРЅРѕР№ С‚Р°Р±Р»РёС†Рµ РЅРµС‚ СЃС‚СЂРѕРє РґР»СЏ РёРјРїРѕСЂС‚Р°.")
        if table.meta.get("schema") == "diagnostics":
            raise ImportValidationError(
                "РЎС‚СЂСѓРєС‚СѓСЂР° СЌС‚РѕРіРѕ PDF РЅРµ СЂР°СЃРїРѕР·РЅР°РЅР° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё. РџСЂРѕРІРµСЂСЊ РґРёР°РіРЅРѕСЃС‚РёС‡РµСЃРєСѓСЋ С‚Р°Р±Р»РёС†Сѓ РІ СЂРµР·СѓР»СЊС‚Р°С‚Рµ РёР·РІР»РµС‡РµРЅРёСЏ Рё РїСЂРёС€Р»Рё С„Р°Р№Р» РґР»СЏ СЂР°СЃС€РёСЂРµРЅРёСЏ С€Р°Р±Р»РѕРЅРѕРІ."
            )

        # Store bank_code in mapping_json so _apply_v2_normalization can use it
        # for fingerprinting without re-fetching the account from DB.
        bank_code = account.bank.code if (account.bank is not None) else None
        current_mapping = {**current_mapping, "bank_code": bank_code}

        # Persist account_id on the session so commit_import can later save
        # the extracted contract_number / statement_account_number back to the
        # account. Without this, the account is always NULL at commit time.
        if session.account_id != payload.account_id:
            session.account_id = payload.account_id
            self.db.add(session)

        detection = self.recognition_service.recognize(table=table)
        merged_detection = {**detection, "selected_table": table.name, "field_mapping": payload.field_mapping}

        preview_rows: list[ImportRow] = []
        summary = {
            "total_rows": len(table.rows),
            "ready_rows": 0,
            "warning_rows": 0,
            "error_rows": 0,
            "duplicate_rows": 0,
            "skipped_rows": 0,
        }

        effective_currency = (payload.currency or account.currency or "RUB").upper()

        # Prefetch once before the loop — accounts/categories/history don't
        # change during a single preview run so fetching them 600 times is waste.
        _accounts_cache = self.enrichment.account_repo.list_by_user(user_id)
        _categories_cache = self.enrichment.category_repo.list(user_id=user_id)
        _history_cache = self.enrichment.transaction_repo.list_transactions(user_id=user_id)[:300]

        for index, raw_row in enumerate(table.rows, start=1):
            normalized: dict[str, Any] = {}
            status = "ready"
            issues: list[str] = []
            unresolved_fields: list[str] = []
            error_message: str | None = None
            duplicate = False

            try:
                normalized = self.normalizer.normalize_row(
                    raw_row=raw_row,
                    field_mapping=payload.field_mapping,
                    date_format=payload.date_format,
                    default_currency=effective_currency,
                )

                enrichment = self.enrichment.enrich_import_row(
                    user_id=user_id,
                    session_account_id=payload.account_id,
                    accounts_cache=_accounts_cache,
                    categories_cache=_categories_cache,
                    history_sample_cache=_history_cache,
                    normalized_payload=normalized,
                )
                normalized.update(enrichment)
                normalized["import_original_description"] = normalized.get("description")

                # Сначала пытаемся взять точное правило TransactionCategoryRule,
                # затем падаем назад на history/fuzzy suggestion из enrichment.
                _norm_desc = enrichment.get("normalized_description") or ""
                _cat_rule = (
                    self.category_rule_repo.get_best_rule(user_id=user_id, normalized_description=_norm_desc)
                    if _norm_desc
                    else None
                )
                if _cat_rule:
                    normalized["category_id"] = _cat_rule.category_id
                    normalized["applied_rule_id"] = _cat_rule.id
                    normalized["applied_rule_category_id"] = _cat_rule.category_id
                else:
                    normalized["category_id"] = enrichment.get("suggested_category_id")
                    normalized.pop("applied_rule_id", None)
                    normalized.pop("applied_rule_category_id", None)

                normalized["operation_type"] = enrichment.get("suggested_operation_type") or self._resolve_operation_type(normalized)

                # §9.3 / §10.5: a loan payment raw-type flags the row for the
                # split-form UI (meta-rule), but the row's operation_type itself
                # must be a real, allowed value (here: transfer). The flag is
                # the trigger — the enrichment's suggested_operation_type does
                # NOT own this decision; we always look at the raw_type.
                _raw_type = str(normalized.get("raw_type") or "").strip().lower()
                if _raw_type in _RAW_TYPES_REQUIRING_CREDIT_SPLIT:
                    normalized["requires_credit_split"] = True
                    # If the enrichment overrode operation_type to something
                    # other than transfer (e.g. inherited a regular-expense
                    # suggestion from history), force it back to transfer so
                    # the split commit branch can find it.
                    normalized["operation_type"] = "transfer"

                # Transfers and non-analytics types don't have categories — clear any
                # rule-matched category that was assigned before operation_type was resolved.
                if str(normalized.get("operation_type") or "") in ("transfer", *NON_ANALYTICS_OPERATION_TYPES):
                    normalized["category_id"] = None
                normalized["type"] = enrichment.get("suggested_type") or normalized.get("direction") or "expense"

                if str(normalized["operation_type"]) == "transfer":
                    # account_id always = session account ("счёт из выписки"), regardless of direction.
                    # target_account_id = the OTHER side of the transfer (source for income, dest for expense).
                    # _create_transfer_pair uses normalized["type"] to determine which side is expense/income.
                    normalized["account_id"] = payload.account_id
                    if str(normalized["type"]) == "income":
                        # Income transfer: session account received money.
                        # target_account_id = source side (where money came from).
                        suggested_source = enrichment.get("suggested_account_id")
                        if suggested_source == payload.account_id:
                            suggested_source = None
                        normalized["target_account_id"] = suggested_source
                    else:
                        # Expense transfer: session account sent money.
                        # target_account_id = destination side.
                        normalized["target_account_id"] = enrichment.get("suggested_target_account_id")

                    # §12.1 / §5.2 v1.1 trigger 6 — enforced in a helper so
                    # the same invariant is unit-tested independently from the
                    # full preview pipeline.
                    status, issues = self._gate_transfer_integrity(
                        normalized=normalized,
                        current_status=status,
                        issues=issues,
                    )
                else:
                    normalized["account_id"] = enrichment.get("suggested_account_id") or payload.account_id
                    normalized["target_account_id"] = enrichment.get("suggested_target_account_id")

                amount_decimal = self._to_decimal(normalized.get("amount"))
                transaction_dt = self._to_datetime(normalized.get("transaction_date") or normalized.get("date"))

                current_operation_type = str(normalized.get("operation_type") or "regular")
                _raw_account_id = normalized.get("account_id")
                if _raw_account_id in (None, "", 0):
                    if current_operation_type == "transfer":
                        # §12.1 + matcher window (PR2): keep at warning during
                        # the preview pass so the debounced cross-session
                        # matcher can still see this row (it filters by
                        # status IN (ready, warning)). Post-matcher cleanup
                        # promotes truly orphan transfers to error via the
                        # `final=True` call to `_gate_transfer_integrity`.
                        issues.append("РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ СЃС‡С‘С‚ РёР· РІС‹РїРёСЃРєРё вЂ” СѓРєР°Р¶Рё РІСЂСѓС‡РЅСѓСЋ.")
                        if status not in ("error", "duplicate"):
                            status = "warning"
                    current_account_id = 0
                else:
                    current_account_id = int(_raw_account_id)

                # Transfer-side duplicate detection happens in transfer_matcher_service
                # (`_detect_committed_duplicates`, debounced after preview): it has skeleton
                # filtering (§8.6), mirror index, and is_secondary marking. Single source
                # of truth — no parallel dedup paths here.

                duplicate = status != "duplicate" and self._find_duplicate(
                    user_id=user_id,
                    account_id=current_account_id,
                    amount=amount_decimal,
                    transaction_date=transaction_dt,
                    skeleton=normalized.get("skeleton"),
                    normalized_description=normalized.get("normalized_description"),
                    transaction_type=str(normalized.get("type") or "expense"),
                )
                if duplicate and payload.skip_duplicates:
                    status = "duplicate"
                    issues.append("РџРѕС…РѕР¶Рµ РЅР° СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓСЋС‰СѓСЋ С‚СЂР°РЅР·Р°РєС†РёСЋ.")
                elif duplicate:
                    status = "warning"
                    issues.append("Р’РѕР·РјРѕР¶РЅС‹Р№ РґСѓР±Р»РёРєР°С‚, РїСЂРѕРІРµСЂСЊ РїРµСЂРµРґ РёРјРїРѕСЂС‚РѕРј.")

                if enrichment.get("needs_manual_review") and status == "ready":
                    status = "warning"

                # Р•СЃР»Рё РЅРµС‚ РїСЂР°РІРёР»Р° РґР»СЏ СЌС‚РѕР№ РѕРїРµСЂР°С†РёРё вЂ” С‚СЂРµР±СѓРµС‚СЃСЏ СЂСѓС‡РЅРѕРµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ РєР°С‚РµРіРѕСЂРёРё.
                _requires_category = (
                    str(normalized.get("operation_type") or "regular") == "regular"
                    and str(normalized.get("operation_type") or "") not in NON_ANALYTICS_OPERATION_TYPES
                )
                if _requires_category and not normalized.get("category_id"):
                    issues.append("РљР°С‚РµРіРѕСЂРёСЏ РЅРµ РѕРїСЂРµРґРµР»РµРЅР° вЂ” СѓРєР°Р¶Рё РІСЂСѓС‡РЅСѓСЋ.")
                    if status == "ready":
                        status = "warning"

                issues.extend(enrichment.get("review_reasons") or [])
                issues.extend(enrichment.get("assignment_reasons") or [])

            except (ImportRowValidationError, ImportValidationError, TransactionValidationError, ValueError, TypeError, InvalidOperation) as exc:
                status = "error"
                error_message = str(exc)
                issues.append(str(exc))

            normalized = self._apply_v2_normalization(
                normalized=normalized,
                session=session,
                fallback_account_id=payload.account_id,
                row_index=index,
                bank_code_override=bank_code,
                user_id=user_id,
                alias_service=self._alias_service,
            )

            issues = list(dict.fromkeys(issue for issue in issues if issue))

            row_confidence = self.confidence.score_row(
                issues=issues,
                unresolved_fields=unresolved_fields,
                detected_fields=payload.field_mapping,
                row_status=status,
            )
            confidence_label = self._confidence_label(row_confidence)

            if status == "ready":
                summary["ready_rows"] += 1
            elif status == "warning":
                summary["warning_rows"] += 1
            elif status == "duplicate":
                summary["duplicate_rows"] += 1
                summary["skipped_rows"] += 1
            else:
                summary["error_rows"] += 1

            preview_row = self.import_repo.create_row(
                session_id=session.id,
                row_index=index,
                raw_data=raw_row,
                normalized_data=normalized,
                status=status,
                errors=issues,
                confidence_score=row_confidence,
                duplicate_candidate=duplicate,
                review_required=status in {"warning", "error"},
            )
            preview_rows.append(preview_row)

        self.import_repo.replace_rows(session=session, rows=preview_rows)

        # Inject account_id and bank_code into mapping_json so downstream
        # services (build_clusters, _apply_v2_normalization) can access them
        # without re-fetching the account from DB.
        merged_detection["account_id"] = payload.account_id
        merged_detection["bank_code"] = bank_code

        self.import_repo.update_session(
            session,
            status="preview_ready",
            mapping_json=merged_detection,
            summary_json=summary,
            account_id=payload.account_id,
            currency=payload.currency,
        )
        self.db.commit()
        self.db.refresh(session)

        # Cross-session transfer matching: debounced, runs in Celery worker.
        # Any state change (this build_preview, account assignment, auto_preview
        # on another session) routes through schedule_transfer_match so a single
        # matcher run converges the state of all active sessions for the user.
        try:
            from app.jobs.transfer_matcher_debounced import schedule_transfer_match
            schedule_transfer_match(user_id)
        except Exception:
            pass

        # In-session refund matching: find expense+refund pairs (same amount,
        # opposite directions, within 14 days) inside this session and write
        # refund_match metadata to both rows. The moderator UI uses it to
        # propose operation_type='refund' even when LLM and Layer 2 missed it.
        self._apply_refund_matches(session_id=session.id)
        self.db.commit()

        # Refund cluster override (И-09). For refund clusters (detected by
        # keyword in normalizer v2, confirmed by cluster assembly), inherit
        # the counterparty + category from the user's purchase history at
        # this merchant and stamp it onto each row. Done AFTER preview/rule
        # application so rule-chain output is overridden for refunds, which
        # are almost never covered by existing rules (rules train on the
        # expense side). Safe to re-run — idempotent.
        self._apply_refund_cluster_overrides(session=session)
        self.db.commit()

        # Response rows are serialized now — transfer_match metadata is filled in
        # by the debounced matcher a few seconds later and picked up via polling.
        updated_rows = self.import_repo.list_rows(session_id=session.id)
        response_rows = [self._serialize_preview_row(row) for row in updated_rows]
        summary = self._recalculate_summary(session.id)

        return {
            "session_id": session.id,
            "status": session.status,
            "summary": summary,
            "detection": merged_detection,
            "rows": response_rows,
        }

    def set_row_label(self, *, user_id: int, row_id: int, user_label: str) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("РЎС‚СЂРѕРєР° РёРјРїРѕСЂС‚Р° РЅРµ РЅР°Р№РґРµРЅР°.")

        _, row = session_row
        normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))

        norm_desc = normalized.get("normalized_description")
        orig_desc = normalized.get("import_original_description") or normalized.get("description")
        category_id = normalized.get("category_id")
        operation_type = normalized.get("operation_type") or "regular"

        if not norm_desc:
            raise ImportValidationError("РЎС‚СЂРѕРєР° РЅРµ СЃРѕРґРµСЂР¶РёС‚ РЅРѕСЂРјР°Р»РёР·РѕРІР°РЅРЅРѕРіРѕ РѕРїРёСЃР°РЅРёСЏ РґР»СЏ СЃРѕР·РґР°РЅРёСЏ РїСЂР°РІРёР»Р°.")
        if not category_id:
            raise ImportValidationError("РЎС‚СЂРѕРєР° РЅРµ СЃРѕРґРµСЂР¶РёС‚ РєР°С‚РµРіРѕСЂРёРё РґР»СЏ СЃРѕР·РґР°РЅРёСЏ РїСЂР°РІРёР»Р°.")
        if operation_type in NON_ANALYTICS_OPERATION_TYPES:
            raise ImportValidationError("Р”Р»СЏ РґР°РЅРЅРѕРіРѕ С‚РёРїР° РѕРїРµСЂР°С†РёРё РїСЂР°РІРёР»Рѕ РєР»Р°СЃСЃРёС„РёРєР°С†РёРё РЅРµ РїСЂРёРјРµРЅСЏРµС‚СЃСЏ.")

        rule = self.category_rule_repo.upsert(
            user_id=user_id,
            normalized_description=norm_desc,
            category_id=int(category_id),
            original_description=orig_desc or None,
            user_label=user_label,
        )
        self.db.commit()
        self.db.refresh(rule)

        return {
            "rule_id": rule.id,
            "normalized_description": rule.normalized_description,
            "original_description": rule.original_description,
            "user_label": rule.user_label,
            "category_id": rule.category_id,
        }

    def commit_import(self, *, user_id: int, session_id: int, import_ready_only: bool = True) -> dict[str, Any]:
        """Commit all eligible rows to Transactions. §5.4 (v1.1):
        - `ready` rows always commit.
        - `warning` rows commit ONLY if the user touched them (individual
          confirm sets `user_confirmed_at`; cluster-level bulk-ack sets
          `cluster_bulk_acked_at`). Untouched warnings stay in the session.
        - `import_ready_only` flag: legacy parameter, retained for backward
          compatibility. When `True`, untouched warnings are skipped (the
          spec-default behaviour). When `False`, same — touched warnings
          always pass, untouched always skip. The "commit everything"
          cross-cluster bypass forbidden by §5.4 does not exist on either
          path.
        """
        session = self.get_session(user_id=user_id, session_id=session_id)
        # Serialize concurrent commits for the same session — prevents accidental
        # double-import when the user double-clicks or two requests arrive together.
        from sqlalchemy import text as _sa_text
        self.db.execute(
            _sa_text("SELECT id FROM import_sessions WHERE id = :sid FOR UPDATE"),
            {"sid": session.id},
        )
        import_rows = self.import_repo.get_rows(session_id=session.id)

        if not import_rows:
            raise ImportValidationError("РќРµС‚ РїРѕРґРіРѕС‚РѕРІР»РµРЅРЅС‹С… СЃС‚СЂРѕРє РґР»СЏ РёРјРїРѕСЂС‚Р°.")

        imported_count = 0
        skipped_count = 0
        duplicate_count = 0
        error_count = 0
        review_count = 0
        parked_count = 0

        for row in import_rows:
            row_status = str(row.status or "").strip().lower()

            if row_status == "parked":
                # Parked rows never become transactions — they are the "undecided"
                # queue across sessions. Analytics read only Transactions, so
                # parked rows are automatically excluded from Поток / FI-score /
                # DTI / Buffer / Health without any aggregation-side filters.
                parked_count += 1
                skipped_count += 1
                continue

            if row_status == "duplicate":
                duplicate_count += 1
                skipped_count += 1
                continue

            if row_status == "error":
                error_count += 1
                skipped_count += 1
                continue

            # §5.4 (v1.1): warning rows only commit if the user explicitly
            # touched them — either via cluster-level bulk-ack (sets
            # `cluster_bulk_acked_at`) or via individual confirm (sets
            # `user_confirmed_at`). Untouched warnings stay in the session.
            # "Commit everything" is forbidden — no cross-cluster auto-pass.
            _norm_for_gate = row.normalized_data or {}
            _bulk_acked = _norm_for_gate.get("cluster_bulk_acked_at")
            _indiv_confirmed = _norm_for_gate.get("user_confirmed_at")
            if row_status == "warning":
                review_count += 1
                if not (_bulk_acked or _indiv_confirmed):
                    # §5.4: untouched warnings stay in the session for the
                    # next moderator pass. import_ready_only is irrelevant
                    # here — both modes skip untouched warnings.
                    skipped_count += 1
                    continue
                # Touch-flagged warning: bulk-acked or individually confirmed.
                # Spec §5.4 says these are committable; commit them regardless
                # of `import_ready_only`. The flag's original "skip even
                # touched" semantics blocked the bulk-ack path entirely,
                # contradicting §5.4 / §10.2 Case B.

            if row_status not in {"ready", "warning"}:
                skipped_count += 1
                continue

            normalized = row.normalized_data or {}

            # §12.1 commit-time guard: a transfer without both accounts must
            # not commit, regardless of how the row got here (warning with a
            # touch flag, ready from a stale cache, manual edit). Run the
            # gate with final=True — same humane reason text as preview &
            # post-matcher paths.
            gate_status, gate_issues = self._gate_transfer_integrity(
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
                    error_count += 1
                    skipped_count += 1
                    continue

            try:
                payloads = self._prepare_transaction_payloads(normalized)
            except (ValueError, TypeError, InvalidOperation) as exc:
                skipped_count += 1
                error_count += 1
                row.status = "error"
                row.errors = list(dict.fromkeys([*(row.errors or []), str(exc)]))
                self.import_repo.update_row(row, status=row.status, errors=row.errors, review_required=True)
                continue

            if not payloads:
                skipped_count += 1
                error_count += 1
                row.status = "error"
                row.errors = list(
                    dict.fromkeys(
                        [*(row.errors or []), "РЎС‚СЂРѕРєР° РЅРµ СЃРѕРґРµСЂР¶РёС‚ РєРѕСЂСЂРµРєС‚РЅС‹С… РґР°РЅРЅС‹С… РґР»СЏ СЃРѕР·РґР°РЅРёСЏ С‚СЂР°РЅР·Р°РєС†РёРё."]
                    )
                )
                self.import_repo.update_row(row, status=row.status, errors=row.errors, review_required=True)
                continue

            try:
                last_transaction = None
                operation_type = str(normalized.get("operation_type") or "regular")
                target_account_id = normalized.get("target_account_id")

                if operation_type == "transfer" and not normalized.get("requires_credit_split") and target_account_id not in (None, "", 0):
                    transfer_match_meta = normalized.get("transfer_match") or {}
                    matched_tx_id = transfer_match_meta.get("matched_tx_id")
                    matched_row_id = transfer_match_meta.get("matched_row_id")

                    linked_tx = None

                    # Path A: cross-session pair — check if partner import row was already
                    # committed (first session committed before this one). Find the phantom
                    # TX created for our account side and link to it instead of creating a
                    # duplicate pair. Balance was already adjusted by the partner's commit.
                    if matched_row_id and not matched_tx_id:
                        linked_tx = self._link_transfer_to_committed_cross_session_pair(
                            user_id=user_id,
                            payload=payloads[0],
                            matched_import_row_id=int(matched_row_id),
                        )

                    # Path B: matched with a committed orphan TX (§10.6 linking).
                    if linked_tx is None and matched_tx_id:
                        linked_tx = self._link_transfer_to_committed_pair(
                            user_id=user_id,
                            payload=payloads[0],
                            committed_tx_id=int(matched_tx_id),
                        )

                    if linked_tx is not None:
                        last_transaction = linked_tx
                    else:
                        expense_tx, income_tx = self._create_transfer_pair(
                            user_id=user_id,
                            payload=payloads[0],
                        )
                        # Link the import row to the TX on its own account side.
                        tx_type = str((payloads[0].get("type") or "expense")).lower()
                        last_transaction = income_tx if tx_type == "income" else expense_tx
                    imported_count += 1
                elif normalized.get("requires_credit_split"):
                    # Ref: financeapp-vault/01-Metrics/Поток.md — decision 2026-04-19
                    # Split into interest expense + principal transfer
                    principal = payloads[0].get("credit_principal_amount")
                    interest = payloads[0].get("credit_interest_amount")
                    eff_credit_acc = payloads[0].get("credit_account_id") or payloads[0].get("target_account_id")
                    from app.models.category import Category as _Category
                    interest_cat = self.db.query(_Category).filter(
                        _Category.user_id == user_id,
                        _Category.is_system.is_(True),
                        _Category.name == "Проценты по кредитам",
                    ).first()
                    interest_cat_id = interest_cat.id if interest_cat else None
                    if principal is not None and interest is not None and eff_credit_acc:
                        # Interest expense
                        interest_payload = {**payloads[0], "operation_type": "regular", "type": "expense",
                            "amount": interest, "category_id": interest_cat_id,
                            "target_account_id": None, "credit_account_id": eff_credit_acc,
                            "credit_principal_amount": None, "credit_interest_amount": None,
                            "description": f"Проценты · {payloads[0].get(chr(39) + "description" + chr(39)) or ""}".strip(" ·"),
                        }
                        # Principal transfer
                        principal_payload = {**payloads[0], "operation_type": "transfer", "type": "expense",
                            "amount": principal, "category_id": None,
                            "target_account_id": eff_credit_acc, "credit_account_id": eff_credit_acc,
                            "credit_principal_amount": None, "credit_interest_amount": None,
                            "description": f"Тело кредита · {payloads[0].get(chr(39) + "description" + chr(39)) or ""}".strip(" ·"),
                        }
                        int_tx = self.transaction_service.create_transaction(user_id=user_id, payload=interest_payload)
                        last_transaction = int_tx
                        self.transaction_service.create_transaction(user_id=user_id, payload=principal_payload)
                        imported_count += 2
                    else:
                        # Missing principal/interest: create as interest expense with needs_review
                        fallback_payload = {**payloads[0], "operation_type": "regular", "type": "expense",
                            "category_id": interest_cat_id, "target_account_id": None,
                            "credit_account_id": eff_credit_acc, "needs_review": True,
                            "credit_principal_amount": None, "credit_interest_amount": None,
                        }
                        last_transaction = self.transaction_service.create_transaction(user_id=user_id, payload=fallback_payload)
                        imported_count += 1
                else:
                    for payload in payloads:
                        part_op = str(payload.get("operation_type") or "regular").lower()
                        if part_op == "transfer" and payload.get("target_account_id") not in (None, "", 0):
                            # Split-part transfer: create a transfer pair just like
                            # the row-level transfer branch above. Each pair counts
                            # as one imported transaction (the income side is
                            # auto-created and isn't a separate user-visible row).
                            expense_tx, _income_tx = self._create_transfer_pair(
                                user_id=user_id,
                                payload=payload,
                            )
                            last_transaction = expense_tx
                        else:
                            last_transaction = self.transaction_service.create_transaction(
                                user_id=user_id,
                                payload=payload,
                            )
                        imported_count += 1
                self.import_repo.update_row(
                    row,
                    status="committed",
                    created_transaction_id=last_transaction.id if last_transaction is not None else None,
                    review_required=False,
                )
                # Refund bind: the refund row arrived with its own fingerprint
                # (direction=income) that has no counterparty binding — we
                # resolved one via brand history at preview time, so create
                # the binding now so a future refund of the same merchant
                # resolves via fingerprint directly (no brand re-search).
                if (
                    str(normalized.get("operation_type") or "") == "refund"
                    and normalized.get("counterparty_id") not in (None, "", 0)
                    and normalized.get("fingerprint")
                ):
                    try:
                        self._counterparty_fp_service.bind(
                            user_id=user_id,
                            fingerprint=str(normalized["fingerprint"]),
                            counterparty_id=int(normalized["counterparty_id"]),
                        )
                    except Exception as exc:  # noqa: BLE001 — never block commit
                        logger.warning(
                            "refund counterparty binding failed row=%s: %s",
                            row.id, exc,
                        )
                category_id = normalized.get("category_id")
                norm_desc = normalized.get("normalized_description")
                orig_desc = normalized.get("import_original_description") or normalized.get("description")
                operation_type = normalized.get("operation_type") or "regular"
                applied_rule_id = normalized.get("applied_rule_id")
                applied_rule_cat = normalized.get("applied_rule_category_id")
                if category_id and norm_desc and operation_type not in NON_ANALYTICS_OPERATION_TYPES:
                    # §10.2 (v1.1) — four cases by (was a rule applied?) × (final == predicted?)
                    # Weight selection per §6.4/§5.4:
                    #   ready                                  → +1.0  (Case A)
                    #   warning + user_confirmed_at  (individual) → +1.0  (Case A — "full touch")
                    #   warning + cluster_bulk_acked_at (bulk)     → +0.5  (Case B)
                    # Rows with cluster_bulk_acked_at already got the 0.5 weight
                    # applied at bulk_apply_cluster — commit MUST NOT re-count
                    # them (would double the strength signal).
                    from app.core.config import settings as _settings
                    from app.services.rule_strength_service import (
                        CONFIRM_WEIGHT_READY, CONFIRM_WEIGHT_WARNING,
                    )
                    _already_counted_at_bulk_ack = bool(_bulk_acked) and not _indiv_confirmed
                    confirm_weight = (
                        CONFIRM_WEIGHT_WARNING if (row_status == "warning" and _bulk_acked and not _indiv_confirmed)
                        else CONFIRM_WEIGHT_READY
                    )
                    rule_svc = RuleStrengthService(self.db, _settings)
                    final_cat = int(category_id)

                    if applied_rule_id is not None and applied_rule_cat is not None and int(applied_rule_cat) == final_cat:
                        # Case A/B: final category matches predicted — confirm R.
                        # Skip if bulk_apply_cluster already applied the 0.5
                        # weight pre-commit (avoids double-count).
                        if _already_counted_at_bulk_ack:
                            pass
                        else:
                            try:
                                rule_svc.on_confirmed(applied_rule_id, confirms_delta=confirm_weight)
                            except RuleNotFound:
                                # Rule deleted between preview and commit — fall through
                                # as if there was no prior rule (Case D).
                                self.category_rule_repo.upsert(
                                    user_id=user_id,
                                    normalized_description=norm_desc,
                                    category_id=final_cat,
                                    original_description=orig_desc or None,
                                )
                    elif applied_rule_id is not None:
                        # Case C: rule applied, user changed the category.
                        # Old rule takes a rejection; new rule R' starts with
                        # this commit as its first confirm (weighted by status).
                        try:
                            rule_svc.on_rejected(applied_rule_id)
                        except RuleNotFound:
                            pass  # old rule gone, ignore the rejection
                        new_rule = self.category_rule_repo.upsert(
                            user_id=user_id,
                            normalized_description=norm_desc,
                            category_id=final_cat,
                            original_description=orig_desc or None,
                        )
                        # `upsert` creates with confirms=1 by default; if the
                        # commit is from a warning row, correct the weight to 0.5.
                        if new_rule is not None and confirm_weight != CONFIRM_WEIGHT_READY:
                            try:
                                new_rule.confirms = confirm_weight
                                self.db.add(new_rule)
                                self.db.flush()
                            except Exception as exc:  # noqa: BLE001 — never block commit
                                logger.warning(
                                    "could not adjust new rule confirm weight: %s", exc,
                                )
                    else:
                        # Case D: no prior rule — user explicitly assigned this
                        # category. New rule, weighted by row status.
                        new_rule = self.category_rule_repo.upsert(
                            user_id=user_id,
                            normalized_description=norm_desc,
                            category_id=final_cat,
                            original_description=orig_desc or None,
                        )
                        if new_rule is not None and confirm_weight != CONFIRM_WEIGHT_READY:
                            try:
                                new_rule.confirms = confirm_weight
                                self.db.add(new_rule)
                                self.db.flush()
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "could not adjust new rule confirm weight: %s", exc,
                                )
            except (TransactionValidationError, ImportValidationError) as exc:
                row.status = "error"
                row.errors = list(dict.fromkeys([*(row.errors or []), str(exc)]))
                self.import_repo.update_row(row, status=row.status, errors=row.errors, review_required=True)
                skipped_count += 1
                error_count += 1

        remaining_rows = [
            row
            for row in self.import_repo.get_rows(session_id=session.id)
            if (row.created_transaction_id is None and str(row.status or "").strip().lower() != "committed")
        ]
        remaining_summary = self._build_summary_from_rows(remaining_rows)
        session.status = "committed" if not remaining_rows else "preview_ready"
        session.summary_json = {
            **(session.summary_json or {}),
            **remaining_summary,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "error_count": error_count,
            "review_count": review_count,
            "parked_count": parked_count,
        }
        parse_settings = session.parse_settings or {}
        contract_number = parse_settings.get("contract_number")
        statement_account_number = parse_settings.get("statement_account_number")
        if session.account_id and (contract_number or statement_account_number):
            account = self.account_repo.get_by_id_and_user(session.account_id, user_id)
            updates: dict[str, Any] = {}
            if account and contract_number and not account.contract_number:
                updates["contract_number"] = contract_number
            if account and statement_account_number and not account.statement_account_number:
                updates["statement_account_number"] = statement_account_number
            if account and updates:
                self.account_repo.update(account, auto_commit=False, **updates)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return {
            "session_id": session.id,
            "status": session.status,
            "summary": remaining_summary,
            "remaining_rows": [self._serialize_preview_row(row) for row in remaining_rows],
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "error_count": error_count,
            "review_count": review_count,
            "parked_count": parked_count,
        }

    def _link_transfer_to_committed_pair(
        self, *, user_id: int, payload: dict[str, Any], committed_tx_id: int
    ) -> TransactionModel | None:
        """Линкует активную сторону transfer к уже закоммиченной orphan-транзакции.

        Сценарий: пользователь сначала закоммитил выписку счёта A. На момент
        коммита второй стороны (счёт B) ещё не было, и транзакции A ушли как
        orphan transfer (target_account_id=NULL, transfer_pair_id=NULL) либо
        как regular income/expense. Затем пользователь импортирует выписку
        счёта B, transfer_matcher свёл строки B с committed-транзакциями A
        и записал matched_tx_id в normalized.transfer_match. Здесь мы:

          1. Создаём ТОЛЬКО активную сторону (B) как transfer.
          2. Достраиваем committed-сторону (A): target_account_id, transfer_pair_id,
             operation_type='transfer', affects_analytics=False.
          3. Применяем balance ТОЛЬКО к активному счёту (B). Баланс счёта A уже
             был учтён при предыдущем коммите (income +amount как у regular,
             так и у transfer-orphan), повторно его не трогаем.

        Возвращает созданную active-сторону или None, если линковка невозможна
        (например, committed_tx уже спарен — fallback на обычное создание пары
        в caller).
        """
        committed_tx = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.id == committed_tx_id,
                TransactionModel.user_id == user_id,
            )
            .first()
        )
        if committed_tx is None:
            return None
        if committed_tx.transfer_pair_id is not None:
            return None

        active_account_id = int(payload["account_id"])
        active_target_account_id = int(payload["target_account_id"])
        if committed_tx.account_id != active_target_account_id:
            return None

        amount = ImportService._to_decimal(payload["amount"])
        if ImportService._to_decimal(committed_tx.amount) != amount:
            return None

        active_type = str(payload.get("type") or "expense")
        committed_type = str(committed_tx.type or "")
        if active_type == committed_type:
            return None

        currency = str(payload.get("currency") or "RUB").upper()
        description = (payload.get("description") or "")[:500]
        transaction_date = ImportService._to_datetime(payload["transaction_date"])
        needs_review = bool(payload.get("needs_review"))
        normalized_description = self.enrichment.normalize_description(description)
        skeleton = payload.get("skeleton") or None

        active_account = self.account_repo.get_by_id_and_user_for_update(active_account_id, user_id)
        if active_account is None:
            raise ImportValidationError("РЎС‡С‘С‚ Р°РєС‚РёРІРЅРѕР№ СЃС‚РѕСЂРѕРЅС‹ РЅРµ РЅР°Р№РґРµРЅ.")

        active_tx = TransactionModel(
            user_id=user_id,
            account_id=active_account_id,
            target_account_id=active_target_account_id,
            amount=amount,
            currency=currency,
            type=active_type,
            operation_type="transfer",
            description=description,
            normalized_description=normalized_description,
            skeleton=skeleton,
            transaction_date=transaction_date,
            needs_review=needs_review,
            affects_analytics=False,
        )
        self.db.add(active_tx)
        self.db.flush()

        committed_tx.target_account_id = active_account_id
        committed_tx.operation_type = "transfer"
        committed_tx.affects_analytics = False
        committed_tx.transfer_pair_id = active_tx.id
        active_tx.transfer_pair_id = committed_tx.id
        self.db.add(committed_tx)
        self.db.add(active_tx)

        if active_type == "expense":
            active_account.balance -= amount
        else:
            active_account.balance += amount
        self.db.add(active_account)

        self.db.commit()
        self.db.refresh(active_tx)
        self.db.refresh(committed_tx)

        return active_tx

    def _link_transfer_to_committed_cross_session_pair(
        self,
        *,
        user_id: int,
        payload: dict[str, Any],
        matched_import_row_id: int,
    ) -> TransactionModel | None:
        """Link to the phantom TX created when the cross-session partner row committed first.

        When both sessions are active and the partner session was committed before
        this one, _create_transfer_pair already created both TXs (one on each account).
        This method finds the TX on OUR account side and returns it so the caller can
        mark this import row as committed without creating a second pair.

        Balance is NOT adjusted — it was already applied by the partner's commit.
        Returns None when the partner row hasn't been committed yet (caller proceeds
        to _create_transfer_pair as usual).
        """
        from app.models.import_row import ImportRow as _ImportRow

        partner_row = (
            self.db.query(_ImportRow)
            .filter(_ImportRow.id == matched_import_row_id)
            .first()
        )
        if partner_row is None or partner_row.created_transaction_id is None:
            return None  # Partner not yet committed — create pair normally

        partner_committed_tx = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.id == partner_row.created_transaction_id,
                TransactionModel.user_id == user_id,
            )
            .first()
        )
        if partner_committed_tx is None or partner_committed_tx.transfer_pair_id is None:
            return None

        our_account_id = int(payload["account_id"])

        # One of {partner_committed_tx, its sibling} lives on our account.
        # Return whichever is ours — that's the phantom created for our side.
        if partner_committed_tx.account_id == our_account_id:
            return partner_committed_tx

        sibling_tx = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.id == partner_committed_tx.transfer_pair_id,
                TransactionModel.user_id == user_id,
            )
            .first()
        )
        if sibling_tx is not None and sibling_tx.account_id == our_account_id:
            return sibling_tx

        return None

    def _create_transfer_pair(
        self, *, user_id: int, payload: dict[str, Any]
    ) -> tuple[TransactionModel, TransactionModel]:
        """Creates two linked Transfer transactions вЂ” one per account side вЂ” and applies balance effects."""
        account_id = int(payload["account_id"])
        target_account_id = int(payload["target_account_id"])
        amount = ImportService._to_decimal(payload["amount"])
        currency = str(payload.get("currency") or "RUB").upper()
        description = (payload.get("description") or "")[:500]
        transaction_date = ImportService._to_datetime(payload["transaction_date"])
        needs_review = bool(payload.get("needs_review"))
        normalized_description = self.enrichment.normalize_description(description)
        # §8.1 dedup key component — carried from the import row's normalized data.
        skeleton = payload.get("skeleton") or None

        # account_id is the SESSION account ("РЎС‡С‘С‚ РёР· РІС‹РїРёСЃРєРё").
        # target_account_id is the OTHER side of the transfer.
        # The 'type' field on the import row determines direction:
        #   type="income": session received money в†’ session is income side, other is expense side.
        #   type="expense": session sent money в†’ session is expense side, other is income side.
        tx_type = str(payload.get("type") or "expense")
        if tx_type == "income":
            expense_account_id = target_account_id
            income_account_id = account_id
        else:
            expense_account_id = account_id
            income_account_id = target_account_id

        expense_account = self.account_repo.get_by_id_and_user_for_update(expense_account_id, user_id)
        income_account = self.account_repo.get_by_id_and_user_for_update(income_account_id, user_id)

        if expense_account is None:
            raise ImportValidationError("РЎС‡С‘С‚ СЃРїРёСЃР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅ.")
        if income_account is None:
            raise ImportValidationError("РЎС‡С‘С‚ РїРѕСЃС‚СѓРїР»РµРЅРёСЏ РЅРµ РЅР°Р№РґРµРЅ.")

        t_expense = TransactionModel(
            user_id=user_id,
            account_id=expense_account_id,
            target_account_id=income_account_id,
            amount=amount,
            currency=currency,
            type="expense",
            operation_type="transfer",
            description=description,
            normalized_description=normalized_description,
            skeleton=skeleton,
            transaction_date=transaction_date,
            needs_review=needs_review,
            affects_analytics=False,
        )
        self.db.add(t_expense)

        t_income = TransactionModel(
            user_id=user_id,
            account_id=income_account_id,
            target_account_id=expense_account_id,
            amount=amount,
            currency=currency,
            type="income",
            operation_type="transfer",
            description=description,
            normalized_description=normalized_description,
            skeleton=skeleton,
            transaction_date=transaction_date,
            needs_review=needs_review,
            affects_analytics=False,
        )
        self.db.add(t_income)

        self.db.flush()  # Assign IDs to both records

        t_expense.transfer_pair_id = t_income.id
        t_income.transfer_pair_id = t_expense.id

        expense_account.balance -= amount
        income_account.balance += amount
        self.db.add(expense_account)
        self.db.add(income_account)

        self.db.commit()
        self.db.refresh(t_expense)
        self.db.refresh(t_income)

        return t_expense, t_income

    @staticmethod
    def _prepare_transaction_payloads(normalized: dict[str, Any]) -> list[dict[str, Any]]:
        if not normalized:
            return []

        transaction_date = normalized.get("transaction_date") or normalized.get("date")
        if transaction_date is None:
            return []

        account_id = normalized.get("account_id")
        amount = normalized.get("amount")
        currency = normalized.get("currency")
        tx_type = normalized.get("type")
        operation_type = normalized.get("operation_type")

        if account_id in (None, "", 0):
            raise ValueError("РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РґР»СЏ С‚СЂР°РЅР·Р°РєС†РёРё.")
        if amount in (None, ""):
            raise ValueError("РќРµ СѓРєР°Р·Р°РЅР° СЃСѓРјРјР° С‚СЂР°РЅР·Р°РєС†РёРё.")
        if not currency:
            raise ValueError("РќРµ СѓРєР°Р·Р°РЅР° РІР°Р»СЋС‚Р° С‚СЂР°РЅР·Р°РєС†РёРё.")
        if not tx_type:
            raise ValueError("РќРµ СѓРєР°Р·Р°РЅ С‚РёРї С‚СЂР°РЅР·Р°РєС†РёРё.")
        if not operation_type:
            raise ValueError("РќРµ СѓРєР°Р·Р°РЅ operation_type С‚СЂР°РЅР·Р°РєС†РёРё.")

        base_payload: dict[str, Any] = {
            "account_id": int(account_id),
            "target_account_id": normalized.get("target_account_id"),
            "credit_account_id": normalized.get("credit_account_id"),
            "category_id": normalized.get("category_id"),
            "amount": ImportService._to_decimal(amount),
            "currency": str(currency).upper(),
            "type": str(tx_type),
            "operation_type": str(operation_type),
            "description": (normalized.get("description") or "")[:1000],
            # §8.1: persist skeleton on the transaction for future-import dedup.
            "skeleton": (normalized.get("skeleton") or None),
            "transaction_date": ImportService._to_datetime(transaction_date),
            "credit_principal_amount": normalized.get("credit_principal_amount"),
            "credit_interest_amount": normalized.get("credit_interest_amount"),
            "counterparty_id": normalized.get("counterparty_id"),
            "debt_partner_id": normalized.get("debt_partner_id"),
            "debt_direction": normalized.get("debt_direction"),
            "needs_review": bool(
                normalized.get("needs_review")
                or normalized.get("review_required")
            ),
        }

        if base_payload.get("target_account_id") not in (None, "", 0):
            base_payload["target_account_id"] = int(base_payload["target_account_id"])
        else:
            base_payload["target_account_id"] = None

        if base_payload.get("credit_account_id") not in (None, "", 0):
            base_payload["credit_account_id"] = int(base_payload["credit_account_id"])
        else:
            base_payload["credit_account_id"] = None

        if base_payload.get("credit_principal_amount") not in (None, ""):
            base_payload["credit_principal_amount"] = ImportService._to_decimal(base_payload["credit_principal_amount"])
        else:
            base_payload["credit_principal_amount"] = None

        if base_payload.get("credit_interest_amount") not in (None, ""):
            base_payload["credit_interest_amount"] = ImportService._to_decimal(base_payload["credit_interest_amount"])
        else:
            base_payload["credit_interest_amount"] = None

        if base_payload.get("category_id") not in (None, "", 0):
            base_payload["category_id"] = int(base_payload["category_id"])
        else:
            base_payload["category_id"] = None

        if base_payload.get("counterparty_id") not in (None, "", 0):
            base_payload["counterparty_id"] = int(base_payload["counterparty_id"])
        else:
            base_payload["counterparty_id"] = None

        if base_payload.get("debt_partner_id") not in (None, "", 0):
            base_payload["debt_partner_id"] = int(base_payload["debt_partner_id"])
        else:
            base_payload["debt_partner_id"] = None

        # §12.2 invariant: debt and counterparty are disjoint. Drop the wrong
        # field at payload assembly so the validator never sees both populated
        # from a stale normalized_data carrying both fields.
        if str(operation_type) == "debt":
            base_payload["counterparty_id"] = None
        else:
            base_payload["debt_partner_id"] = None


        split_items = normalized.get("split_items") or []
        if str(operation_type) == "regular" and isinstance(split_items, list) and len(split_items) >= 2:
            # Each part may carry its OWN operation_type. Inherit common fields
            # from base_payload (account, currency, date), but rebuild the
            # type-specific slice from the part's own values.
            payloads: list[dict[str, Any]] = []
            for item in split_items:
                if not isinstance(item, dict):
                    raise ValueError("Разбивка заполнена некорректно.")
                part_op = str(item.get("operation_type") or "regular").lower()
                split_amount = ImportService._to_decimal(item.get("amount"))
                description = (item.get("description") or base_payload["description"] or "")[:1000]
                part_category_id = item.get("category_id")
                part_target_account_id = item.get("target_account_id")
                part_debt_direction = item.get("debt_direction")
                part_counterparty_id = item.get("counterparty_id")
                part_debt_partner_id = item.get("debt_partner_id")

                if part_op in ("regular", "refund") and part_category_id in (None, "", 0):
                    raise ValueError("В разбивке для каждой части нужна категория.")
                if part_op == "transfer" and part_target_account_id in (None, "", 0):
                    raise ValueError("В части-переводе нужно указать счёт назначения.")
                if part_op == "debt":
                    if not part_debt_direction:
                        raise ValueError("В части-долге нужно указать направление долга.")
                    if part_debt_partner_id in (None, "", 0):
                        raise ValueError("В части-долге нужно указать дебитора / кредитора.")

                # type/direction for the part: regular/debt/transfer keep the
                # original direction (expense — money leaves the source account).
                # refund inverts to income (money returned to the source account).
                if part_op == "refund":
                    part_type = "income"
                else:
                    part_type = base_payload["type"]

                # Counterparty and debt_partner are mutually exclusive per part:
                # debt parts route to a DebtPartner (the debtor / creditor),
                # non-debt parts keep Counterparty (the merchant / service).
                # Drop the wrong field to avoid validator rejection downstream.
                if part_op == "debt":
                    part_counterparty_id = None
                else:
                    part_debt_partner_id = None

                payloads.append({
                    **base_payload,
                    "operation_type": part_op,
                    "type": part_type,
                    "amount": split_amount,
                    "description": description,
                    "category_id": int(part_category_id) if part_category_id not in (None, "", 0) else None,
                    "target_account_id": int(part_target_account_id) if part_target_account_id not in (None, "", 0) else None,
                    "debt_direction": str(part_debt_direction).lower() if part_debt_direction else None,
                    "counterparty_id": int(part_counterparty_id) if part_counterparty_id not in (None, "", 0) else None,
                    "debt_partner_id": int(part_debt_partner_id) if part_debt_partner_id not in (None, "", 0) else None,
                    # Credit/investment slice fields — not relevant for individual
                    # parts; they always come from the original row, not split.
                    "credit_account_id": None,
                    "credit_principal_amount": None,
                    "credit_interest_amount": None,
                })
            return payloads
        return [base_payload]

    @staticmethod
    def _to_decimal(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        if isinstance(value, str):
            cleaned = value.strip().replace(" ", "").replace(",", ".")
            if not cleaned:
                raise ValueError("РџСѓСЃС‚РѕРµ Р·РЅР°С‡РµРЅРёРµ СЃСѓРјРјС‹.")
            return Decimal(cleaned)
        raise TypeError("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С„РѕСЂРјР°С‚ СЃСѓРјРјС‹.")

    @staticmethod
    def _to_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise TypeError("РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С„РѕСЂРјР°С‚ РґР°С‚С‹ С‚СЂР°РЅР·Р°РєС†РёРё.")

    def _session_to_upload_response(self, session: ImportSession) -> dict[str, Any]:
        ps = session.parse_settings or {}
        detection = session.mapping_json or ps.get("detection", {})
        extraction_meta = ps.get("extraction", {})
        tables = ps.get("tables", [])
        primary_table_name = ps.get("table_names", [None])[0]
        sample_rows: list = []
        total_rows = 0
        detected_columns: list = session.detected_columns or []
        for t in tables:
            if isinstance(t, dict) and t.get("name") == primary_table_name:
                sample_rows = t.get("rows", [])[:5]
                total_rows = len(t.get("rows", []))
                break

        return {
            "session_id": session.id,
            "filename": session.filename,
            "source_type": session.source_type,
            "status": session.status,
            "detected_columns": detected_columns,
            "sample_rows": sample_rows,
            "total_rows": total_rows,
            "extraction": {
                **extraction_meta,
                "tables_found": len(tables),
                "primary_table": primary_table_name,
            },
            "detection": detection,
            "suggested_account_id": session.account_id,
            "contract_number": ps.get("contract_number"),
            "contract_match_reason": None,
            "contract_match_confidence": None,
            "statement_account_number": ps.get("statement_account_number"),
            "statement_account_match_reason": None,
            "statement_account_match_confidence": None,
        }

    @staticmethod
    def _detect_extension(filename: str) -> str:
        _, ext = os.path.splitext((filename or "").lower())
        return ext.lstrip(".")

    @staticmethod
    def _pick_primary_table(extraction: ExtractionResult):
        return max(
            extraction.tables,
            key=lambda table: (
                1 if table.meta.get("schema") == "normalized_transactions" else 0,
                table.confidence,
                len(table.rows),
            ),
        )

    @staticmethod
    def _serialize_tables(tables: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                "name": table.name,
                "columns": table.columns,
                "rows": table.rows,
                "confidence": table.confidence,
                "meta": table.meta,
            }
            for table in tables
        ]

    @staticmethod
    def _load_tables_from_session(session: ImportSession) -> list[Any]:
        parse_settings = session.parse_settings or {}
        tables = parse_settings.get("tables") or []
        return [
            type(
                "SessionTable",
                (),
                {
                    "name": item.get("name", "table"),
                    "columns": item.get("columns", []),
                    "rows": item.get("rows", []),
                    "confidence": item.get("confidence", 0.0),
                    "meta": item.get("meta", {}),
                },
            )()
            for item in tables
        ]

    @staticmethod
    def _encode_source(*, raw_bytes: bytes, source_type: str) -> dict[str, str]:
        encoded = base64.b64encode(raw_bytes).decode("utf-8")
        return {
            "storage": "inline_base64",
            "content": encoded,
            "source_type": source_type,
        }

    def _find_duplicate(
        self,
        *,
        user_id: int,
        account_id: int,
        amount: Decimal,
        transaction_date: datetime,
        skeleton: str | None,
        normalized_description: str | None,
        transaction_type: str = "expense",
    ) -> bool:
        """§8.1 deduplication against committed transactions.

        Primary discriminant is **skeleton** — the v2 normalizer's
        placeholder-rich form, which collapses identifier variation (same
        merchant, different phone/contract) into one key. This is what the
        spec calls for.

        The function is layered:
          1. (account + amount + date ±1 + skeleton) — strict match. Bank
             timezone drift can shift `transaction_date` by a day, so we
             accept ±1 day here. No description filter — user may have
             renamed the original transaction.
          2. Fallback for pre-0052 transactions whose skeleton is NULL:
             widen to ±3 days and match on `normalized_description`. Legacy
             rows keep working until the backfill script populates skeleton.
        """
        incoming_skeleton = (skeleton or "").strip()
        incoming_norm = (normalized_description or "").strip().lower()

        # Level 1: skeleton match in ±1 day window.
        if incoming_skeleton:
            exact_candidates = self.transaction_repo.find_nearby_duplicates(
                user_id=user_id,
                account_id=account_id,
                amount=amount,
                transaction_date=transaction_date,
                skeleton=incoming_skeleton,
                days_window=1,
                transaction_type=transaction_type,
            )
            if exact_candidates:
                return True

            # Level 2a: skeleton match widened to ±3 days — covers cases where
            # a bank posted the same operation with an unusual delay.
            wide_candidates = self.transaction_repo.find_nearby_duplicates(
                user_id=user_id,
                account_id=account_id,
                amount=amount,
                transaction_date=transaction_date,
                skeleton=incoming_skeleton,
                days_window=3,
                transaction_type=transaction_type,
            )
            if wide_candidates:
                return True

        # Level 2b: legacy fallback for transactions imported before the
        # skeleton column existed (skeleton IS NULL). Falls back to
        # normalized_description match in ±3 days window. When the backfill
        # script finishes, this branch rarely fires.
        if not incoming_norm:
            return False
        legacy_candidates = self.transaction_repo.find_nearby_duplicates(
            user_id=user_id,
            account_id=account_id,
            amount=amount,
            transaction_date=transaction_date,
            days_window=3,
            transaction_type=transaction_type,
        )
        return any(
            item.skeleton is None
            and (item.normalized_description or "").strip().lower() == incoming_norm
            for item in legacy_candidates
        )

    @staticmethod
    def _apply_v2_normalization(
        normalized: dict[str, Any],
        session: ImportSession,
        fallback_account_id: int | None,
        row_index: int,
        bank_code_override: str | None = None,
        user_id: int | None = None,
        alias_service: "FingerprintAliasService | None" = None,
    ) -> dict[str, Any]:
        """Run normalizer_v2 on top of the v1 normalized dict.

        Additive: only the v2 keys (skeleton / fingerprint / tokens /
        normalizer_version) are written via NormalizedDataV2.merge_into.
        Any failure is logged and swallowed — v2 must never break import.
        """
        try:
            description = (
                normalized.get("import_original_description")
                or normalized.get("description")
                or ""
            )
            # Prefer explicit bank_code_override (passed directly from build_preview
            # before mapping_json is saved), then mapping_json, then source_type.
            resolved_bank_code: str | None = (
                bank_code_override
                or (session.mapping_json or {}).get("bank_code")
            )
            # Use resolved code for fingerprint; fall back to source_type sentinel
            # only for the fingerprint string (not stored as bank_code).
            bank = resolved_bank_code or str(getattr(session, "source_type", None) or "unknown")
            account_id = int(normalized.get("account_id") or fallback_account_id or 0)
            # "unknown" when direction isn't known yet — NOT "expense". A silent
            # "expense" default would make the fingerprint unstable: once the
            # direction is corrected later, the same row's fingerprint would
            # drift, breaking the link to any rule already learned from it.
            # "unknown" records the absence explicitly; when a real direction
            # appears, the fingerprint shifts transparently.
            direction = str(
                normalized.get("type")
                or normalized.get("direction")
                or "unknown"
            )

            tokens = v2_extract_tokens(description)
            skeleton = v2_normalize_skeleton(description, tokens)
            # For transfer-like rows, fold the recipient identifier (phone /
            # contract / card) into the fingerprint in raw form. Otherwise
            # every "Внешний перевод по номеру телефона" collapses into one
            # giant cluster, even though each recipient is a separate pattern
            # (аренда брату vs мама vs разовые). See project_bulk_clusters.md.
            transfer_identifier = None
            if v2_is_transfer_like(description, normalized.get("operation_type")):
                transfer_identifier = v2_pick_transfer_identifier(tokens)
            fp = v2_fingerprint(
                bank, account_id, direction, skeleton,
                tokens.contract, transfer_identifier=transfer_identifier,
            )

            # Refund detection. The flag rides inside normalized_data_json so
            # build_clusters can mark the whole cluster as a refund without
            # re-parsing the description. Brand lookup is best-effort — a
            # None value just means the clusterer falls back to manual
            # counterparty selection (attention bucket).
            refund_flag = v2_is_refund_like(description, normalized.get("operation_type"))
            refund_brand = v2_pick_refund_brand(description, tokens) if refund_flag else None

            # Alias resolution (Level 3 cluster-merge): if the user previously
            # attached this fingerprint to another cluster, redirect here so
            # the row joins its target cluster automatically on next import.
            if alias_service is not None and user_id is not None:
                try:
                    resolved_fp = alias_service.resolve(
                        user_id=user_id, fingerprint=fp,
                    )
                    if resolved_fp and resolved_fp != fp:
                        fp = resolved_fp
                except Exception as exc:  # noqa: BLE001 — never block import
                    logger.warning(
                        "fingerprint alias resolve failed row=%s: %s", row_index, exc,
                    )

            model = NormalizedDataV2.from_tokens(
                tokens=tokens, skeleton=skeleton, fingerprint=fp,
                is_refund=refund_flag, refund_brand=refund_brand,
            )
            result = model.merge_into(normalized)
            # Persist resolved bank_code so build_clusters can read it from
            # normalized_data_json without re-fetching the account from DB.
            if resolved_bank_code:
                result["bank_code"] = resolved_bank_code
            return result
        except Exception as exc:  # noqa: BLE001 — v2 must never break import
            logger.warning(
                "v2 normalization failed for row %s: %s", row_index, exc,
            )
            return normalized

    @staticmethod
    def _resolve_operation_type(normalized: dict[str, Any]) -> str:
        raw_type = str(normalized.get("raw_type") or "").strip().lower()
        if raw_type in RAW_TYPE_TO_OPERATION_TYPE:
            return RAW_TYPE_TO_OPERATION_TYPE[raw_type]

        direction = str(normalized.get("direction") or "").strip().lower()
        operation_type = str(normalized.get("operation_type") or "").strip().lower()
        candidate = operation_type or direction or "regular"

        if candidate not in ALLOWED_OPERATION_TYPES:
            return "regular"
        return candidate

    @staticmethod
    def _confidence_label(score: Any) -> str:
        try:
            value = float(score or 0.0)
        except (TypeError, ValueError):
            value = 0.0

        if value >= 0.85:
            return "high"
        if value >= 0.6:
            return "medium"
        return "low"
