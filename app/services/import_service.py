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
from app.schemas.imports import (
    DuplicateAction,
    ExistingProgress,
    ImportMappingRequest,
    ImportPreviewSummary,
    ImportRowUpdateRequest,
)
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
from app.services.import_normalization import (
    normalize as _normalize_import_row,
    apply_decisions as _apply_import_decisions,
    _CREDIT_PAYMENT_KEYWORDS,
)
from app.schemas.normalized_row import EnrichmentSuggestion as _EnrichmentSuggestion


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


class BankUnsupportedError(Exception):
    """Upload was matched to an account whose bank has no tested extractor.

    Etap 1 Step 1.6 guard. Carries enough fields for the route to render a
    structured 415 response that the frontend uses to surface the
    "Запросить поддержку банка" modal pre-filled with this bank.

    `extractor_status` is included so the UI can distinguish
    `pending` (whitelist candidate) from `in_review` ("скоро") and
    `broken` ("временно не работает") and copy-tweak the error accordingly.
    """

    def __init__(self, *, bank_id: int, bank_name: str, extractor_status: str) -> None:
        self.bank_id = bank_id
        self.bank_name = bank_name
        self.extractor_status = extractor_status
        super().__init__(
            f"Импорт из банка «{bank_name}» пока не поддерживается "
            f"(статус: {extractor_status})."
        )


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
        # Transfer-pair create/link branches (spec §10.6, §10.7, §12.9, §12.12)
        # — extracted into TransferLinkingService 2026-04-29 (§1 backlog step 2).
        from app.services.transfer_linking_service import TransferLinkingService
        self.transfer_linker = TransferLinkingService(
            db, normalize_description=self.enrichment.normalize_description,
        )
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
        force_new: bool = False,
    ) -> dict[str, Any]:
        return self.upload_file(
            user_id=user_id,
            filename=filename,
            raw_bytes=raw_bytes,
            delimiter=delimiter,
            has_header=has_header,
            force_new=force_new,
        )

    def upload_file(
        self,
        *,
        user_id: int,
        filename: str,
        raw_bytes: bytes,
        delimiter: str | None = None,
        has_header: bool = True,
        force_new: bool = False,
    ) -> dict[str, Any]:
        """Upload a bank statement file.

        Этап 0.5: explicit duplicate-detection signal in the response.
            * If an UNCOMMITTED session with the same `file_hash` exists,
              return `action_required="choose"` with progress counters so the
              UI can show "Открыть существующую / Перезаписать / Отмена".
            * If only a COMMITTED session exists with the same hash, return
              `action_required="warn"` with no `session_id` — the UI shows a
              soft "уже импортирована" banner with `[Загрузить как новую] /
              [Отмена]`.
            * `force_new=True` bypasses both checks and creates a new
              parallel session — used after the user picks "Перезаписать"
              or "Загрузить как новую" in the modal.

        "Перезаписать" is intentionally NON-destructive: the existing
        session is preserved and lives in the queue. The user reconciles
        in the queue UI which session to keep.
        """
        file_hash = hashlib.sha256(raw_bytes).hexdigest()

        if not force_new:
            duplicates = self.import_repo.find_by_file_hash(
                user_id=user_id, file_hash=file_hash, include_committed=True,
            )
            active_dups = [s for s in duplicates if s.status != "committed"]
            committed_dups = [s for s in duplicates if s.status == "committed"]
            if len(active_dups) > 1:
                # Race-condition signal: two parallel upload tabs both passed
                # the duplicate check, both created sessions. Log so we can
                # decide later if a partial UNIQUE INDEX is worth a migration.
                logger.warning(
                    "multiple uncommitted sessions for one file_hash — possible race",
                    extra={
                        "user_id": user_id,
                        "file_hash": file_hash,
                        "count": len(active_dups),
                        "session_ids": [s.id for s in active_dups],
                    },
                )
            if active_dups:
                existing = active_dups[0]
                return self._session_to_upload_response(
                    existing,
                    action_required=DuplicateAction.CHOOSE,
                    existing_progress=self._count_existing_progress(existing.id),
                    existing_status=existing.status,
                    existing_created_at=existing.created_at,
                )
            if committed_dups:
                existing = committed_dups[0]
                return self._session_to_upload_response(
                    existing,
                    action_required=DuplicateAction.WARN,
                    existing_status=existing.status,
                    existing_created_at=existing.created_at,
                )

        extension = self._detect_extension(filename)
        extractor = self.extractors.get(extension)
        if extractor is None:
            raise ImportValidationError(f"Формат .{extension} не поддерживается для импорта.")

        try:
            extraction = extractor.extract(
                filename=filename,
                raw_bytes=raw_bytes,
                options={"delimiter": delimiter, "has_header": has_header},
            )
        except Exception as exc:
            raise ImportValidationError(f"Не удалось обработать файл {filename}: {exc}") from exc

        if not extraction.tables:
            raise ImportValidationError('Не удалось извлечь данные из файла.')

        primary_table = self._pick_primary_table(extraction)
        detection = self.recognition_service.recognize(table=primary_table)
        contract_number = extraction.meta.get("contract_number")
        contract_match_reason = extraction.meta.get("contract_match_reason")
        contract_match_confidence = extraction.meta.get("contract_match_confidence")
        statement_account_number = extraction.meta.get("statement_account_number")
        statement_account_match_reason = extraction.meta.get("statement_account_match_reason")
        statement_account_match_confidence = extraction.meta.get("statement_account_match_confidence")
        # Auto-account-recognition Шаг 1: extractor classifies bank + type up
        # front; we surface both into the response and use them for Level-3
        # fallback below. Defaults are conservative — `unknown` for bank means
        # "extractor didn't recognize", `None` for type means "extractor couldn't
        # disambiguate" (e.g. T-Bank universal pipeline doesn't yet classify
        # debit vs credit). See pdf_extractor.BANK_CODE_* / ACCOUNT_TYPE_*.
        bank_code = extraction.meta.get("bank_code")
        account_type_hint = extraction.meta.get("account_type_hint")
        suggested_account_id: int | None = None
        suggested_account_match_reason: str | None = None
        suggested_account_match_confidence: float | None = None
        suggested_bank_id: int | None = None
        account_candidates: list[dict[str, Any]] = []
        requires_account_creation = False

        # Level 1 — exact contract_number match (highest trust, indexed lookup
        # with three internal levels: Account.contract_number → active session
        # parse_settings → tokens.contract inside import rows).
        if contract_number and user_id:
            matched_account = self.account_repo.find_by_contract_number(
                user_id=user_id,
                contract_number=contract_number,
            )
            if matched_account:
                suggested_account_id = matched_account.id
                suggested_account_match_reason = contract_match_reason
                suggested_account_match_confidence = contract_match_confidence

        # Level 2 — exact statement_account_number match (Sber 20-digit РФ
        # лицевой счёт, Ozon Номер лицевого счёта).
        if suggested_account_id is None and statement_account_number and user_id:
            matched_account = self.account_repo.find_by_statement_account_number(
                user_id=user_id,
                statement_account_number=statement_account_number,
            )
            if matched_account:
                suggested_account_id = matched_account.id
                suggested_account_match_reason = statement_account_match_reason
                suggested_account_match_confidence = statement_account_match_confidence

        # Level 3 — bank + account_type fallback (Шаг 2). Only fires when the
        # exact-identifier lookups above didn't match. Resolves the user's
        # active accounts at the detected bank, optionally narrowed by type:
        #   • exactly 1   → auto-attach (lower confidence than Level 1/2 — we
        #                   matched on profile, not on a unique identifier).
        #   • 2 or more   → return as account_candidates for the UI picker;
        #                   we don't auto-pick because the user may not want
        #                   the most-recent one.
        #   • 0           → propose creating a new account, pre-fill
        #                   bank_id + account_type for the modal.
        # Skipped entirely when bank_code is missing or 'unknown' — universal
        # pipeline didn't recognise the bank, so guessing by account_type
        # alone (across all the user's banks) would mismatch wildly.
        if (
            suggested_account_id is None
            and user_id
            and bank_code
            and bank_code != "unknown"
        ):
            from app.repositories.bank_repository import BankRepository
            bank_repo = BankRepository(self.db)
            bank = bank_repo.get_by_code(bank_code)
            if bank is not None:
                suggested_bank_id = bank.id
                matches = self.account_repo.list_active_by_bank_and_type(
                    user_id=user_id,
                    bank_id=bank.id,
                    account_type=account_type_hint,
                )
                if len(matches) == 1:
                    sole = matches[0]
                    suggested_account_id = sole.id
                    # Reason is intentionally human-readable — the frontend
                    # surfaces it directly under the "ready to import" status
                    # ("Найден единственный счёт «Sber Кредитная карта»").
                    type_label = account_type_hint or "счёт"
                    suggested_account_match_reason = (
                        f"Найден единственный {type_label} в банке «{bank.name}»"
                    )
                    # 0.7 stays comfortably below Level 1/2's 0.93–0.99 — the
                    # match is profile-based and the user might still own
                    # another similar account at this bank that just doesn't
                    # exist in our DB yet.
                    suggested_account_match_confidence = 0.7
                elif len(matches) >= 2:
                    account_candidates = [
                        {
                            "id": acc.id,
                            "name": acc.name,
                            "bank_id": acc.bank_id,
                            "bank_name": getattr(acc.bank, "name", None) if getattr(acc, "bank", None) else None,
                            "account_type": acc.account_type,
                            "is_closed": bool(acc.is_closed),
                            "contract_number": acc.contract_number,
                            "statement_account_number": acc.statement_account_number,
                        }
                        for acc in matches
                    ]
                else:
                    # Zero matches — user has no account at this bank+type.
                    # The UI uses this + suggested_bank_id + account_type_hint
                    # to offer "Create account «Sber Кредитная карта» now"
                    # without making the user pick the bank manually.
                    requires_account_creation = True

        # Этап 1 Шаг 1.6 — bank-supported guard. Fires only when the upload
        # auto-matched an account (via contract_number / statement_account_number)
        # AND that account's bank lacks a tested extractor. Three reasons to
        # gate here, not earlier:
        #   1. We need extraction.meta to know which account matched — there's
        #      no cheaper way to detect the bank for a generic CSV.
        #   2. Uploads that DON'T auto-match (no contract on file, brand-new
        #      bank, manual-only flow) fall through — the user assigns an
        #      account in the queue, and the frontend disclaimer at /import
        #      catches unsupported-bank intent BEFORE upload click.
        #   3. Sessions for unsupported banks are NEVER created in the DB,
        #      so the dedup check above can't ever match an unsupported
        #      session — bank guard before/after dedup is moot semantically.
        if suggested_account_id is not None:
            matched = self.account_repo.get_by_id_and_user(
                account_id=suggested_account_id, user_id=user_id,
            )
            bank = matched.bank if matched is not None else None
            if bank is not None and bank.extractor_status != "supported":
                raise BankUnsupportedError(
                    bank_id=bank.id,
                    bank_name=bank.name,
                    extractor_status=bank.extractor_status,
                )

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
            # Auto-account-recognition Шаг 2 — extractor-derived bank/type +
            # Level-3 fallback results. The fields are populated together so
            # the frontend has a single read path regardless of which level
            # produced the match. See `_resolve_suggested_account` flow above.
            "bank_code": bank_code,
            "account_type_hint": account_type_hint,
            "suggested_account_match_reason": suggested_account_match_reason,
            "suggested_account_match_confidence": suggested_account_match_confidence,
            "suggested_bank_id": suggested_bank_id,
            "account_candidates": account_candidates,
            "requires_account_creation": requires_account_creation,
            # Этап 0.5 — duplicate-detection signals. Always None on the
            # fresh-upload path (we only got here because no duplicate matched).
            # Kept aligned with `_session_to_upload_response` so the response
            # contract is uniform regardless of which branch produced it.
            "action_required": None,
            "existing_progress": None,
            "existing_status": None,
            "existing_created_at": None,
        }

    def get_session(self, *, user_id: int, session_id: int) -> ImportSession:
        session = self.import_repo.get_session(session_id=session_id, user_id=user_id)
        if session is None:
            raise ImportNotFoundError('Сессия импорта не найдена.')
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

    def get_queue_bulk_clusters(self, *, user_id: int) -> dict[str, Any]:
        """Cross-session bulk clusters (v1.23). Same shape as the
        single-session `get_bulk_clusters`, but the fingerprint clusters
        come from every preview-ready session of the user, brand groups
        span sessions, and counterparty groups aggregate naturally
        (FP-binding is already user-scoped, not session-scoped).

        `session_id` is omitted from the response — the queue is
        session-agnostic from the UI's perspective.
        """
        from app.services.import_cluster_service import ImportClusterService

        cluster_svc = ImportClusterService(self.db)
        fp_clusters, brand_clusters, counterparty_groups = (
            cluster_svc.build_bulk_clusters_for_user(user_id=user_id)
        )

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
            "fingerprint_clusters": fp_dicts,
            "brand_clusters": brand_dicts,
            "counterparty_groups": counterparty_dicts,
        }

    def bulk_apply_cluster(
        self, *, user_id: int, session_id: int, payload: Any,
    ) -> dict[str, Any]:
        """Apply one moderator action across many rows in a cluster (spec §5.4).

        Delegates to BulkApplyOrchestrator (extracted 2026-04-29 as §1 backlog
        step 3). Wrapper kept stable so API/tests calling
        `ImportService.bulk_apply_cluster` continue to work unchanged.
        """
        from app.services.bulk_apply_orchestrator import BulkApplyOrchestrator
        orchestrator = BulkApplyOrchestrator(
            self.db,
            import_repo=self.import_repo,
            category_rule_repo=self.category_rule_repo,
            counterparty_fp_service=self._counterparty_fp_service,
            counterparty_id_service=self._counterparty_id_service,
            update_row_fn=self.update_row,
            recalculate_summary_fn=self._recalculate_summary,
            get_session_fn=self.get_session,
        )
        return orchestrator.apply(user_id=user_id, session_id=session_id, payload=payload)

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

        existing_op = str(normalized.get("operation_type") or "").lower()
        user_already_confirmed = bool(normalized.get("user_confirmed_at"))

        if user_already_confirmed:
            # Row was individually confirmed via the pencil editor — the user
            # explicitly chose operation_type and category. Preserve those
            # choices: only attach the counterparty so the row is grouped
            # correctly in the UI, without overriding anything else.
            row_payload = ImportRowUpdateRequest(
                counterparty_id=counterparty_id,
                action="confirm",
            )
        else:
            # Preserve a refund classification if the row carries one — attach
            # must not silently demote a refund to a regular income row.
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
        # Suggested-bank lookup is one DB query per distinct bank_code on the
        # response; cache it locally so a queue of N Tbank sessions doesn't
        # repeat the same lookup N times.
        from app.repositories.bank_repository import BankRepository
        bank_repo = BankRepository(self.db)
        bank_id_by_code: dict[str, int | None] = {}

        items = []
        for session in sessions:
            rows = self.import_repo.list_rows(session_id=session.id)
            summary = session.summary_json or {}
            auto_preview = (summary.get("auto_preview") or {}).get("status")
            transfer_match = (summary.get("transfer_match") or {}).get("status")

            # Auto-account-recognition Шаг 4 (2026-05-06). Surface the
            # extractor's bank/account_type detection on every queue entry
            # so the frontend can render an inline «Это <Bank> <Type>?»
            # prompt without a per-session getImportSession() roundtrip.
            #
            # Refine the persisted account_type_hint at read time: the rules
            # in `_refine_account_type_by_contract` evolve as we learn more
            # about each bank's contract format (Ozon «КК», T-Bank statement
            # fallback, Yandex no-credit-card coercion — all added 2026-05-06).
            # Doing it on-the-fly avoids a DB migration: any session uploaded
            # before the latest refine ruleset still presents the correct
            # type to the queue UI without re-extracting the PDF.
            from app.services.import_extractors.pdf_extractor import PdfExtractor
            extraction = (session.parse_settings or {}).get("extraction") or {}
            bank_code = extraction.get("bank_code")
            stored_type_hint = extraction.get("account_type_hint")
            contract_number = extraction.get("contract_number")
            statement_account_number = extraction.get("statement_account_number")

            # Re-extract contract from the stored preview_text when it's
            # missing — covers sessions uploaded before regex fixes (e.g.
            # Ozon «Номер договора: № …» pattern was added 2026-05-06).
            # preview_text is the first 40 raw_lines of the PDF, which is
            # exactly the window `_extract_contract_number_details` needs.
            if not contract_number:
                preview_text = extraction.get("preview_text")
                if preview_text:
                    raw_lines = [ln for ln in str(preview_text).splitlines() if ln.strip()]
                    re_contract, _, _ = PdfExtractor._extract_contract_number_details(raw_lines)
                    if re_contract:
                        contract_number = re_contract

            account_type_hint = PdfExtractor._refine_account_type_by_contract(
                bank_code=bank_code,
                contract_number=contract_number,
                statement_account_number=statement_account_number,
                default=stored_type_hint,
            )

            suggested_bank_id: int | None = None
            if bank_code and bank_code != "unknown":
                if bank_code not in bank_id_by_code:
                    bank = bank_repo.get_by_code(bank_code)
                    bank_id_by_code[bank_code] = bank.id if bank else None
                suggested_bank_id = bank_id_by_code[bank_code]

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
                "warning_count": sum(1 for r in rows if r.status == "warning"),
                "error_count": sum(1 for r in rows if r.status == "error"),
                "auto_preview_status": auto_preview,
                "transfer_match_status": transfer_match,
                "bank_code": bank_code,
                "account_type_hint": account_type_hint,
                "contract_number": contract_number,
                "statement_account_number": statement_account_number,
                "suggested_bank_id": suggested_bank_id,
            })
        return {"sessions": items, "total": len(items)}

    def delete_session(self, *, user_id: int, session_id: int) -> None:
        session = self.import_repo.get_session(session_id=session_id, user_id=user_id)
        if session is None:
            raise ImportNotFoundError('Сессия импорта не найдена.')
        self.import_repo.delete_session(session)
        self.db.commit()


    def send_row_to_review(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError('Строка импорта не найдена.')

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError('Строка уже импортирована и не может быть отправлена на проверку.')
        if row_status == "duplicate":
            raise ImportValidationError('Дубликат нельзя отправить на проверку вручную.')
        if row_status == "error":
            raise ImportValidationError('Строка уже содержит ошибку и будет доступна в проверке автоматически.')
        if row_status != "ready":
            raise ImportValidationError("На проверку можно отправить только строки со статусом 'Готово'.")

        issues = list(dict.fromkeys([*(getattr(row, "errors", None) or []), 'Отправлено на проверку вручную.']))
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
        """LLM moderation is disabled (decision 2026-05-03).

        Kept as a no-op so any in-flight UI calls reach a deterministic stub
        instead of throwing. The Celery task is no longer enqueued and the
        endpoint returns 410 Gone — see app/api/v1/imports.py.
        """
        session = self.get_session(user_id=user_id, session_id=session_id)
        return {"session_id": session.id, "status": "disabled"}

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

    def unpair_row(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        """Remove a transfer/duplicate pairing from a row and return it to 'warning'
        so the user can re-categorise it as a regular expense/income.

        Clears: transfer_match, operation_type, target_account_id, was_orphan_transfer.
        Works on rows with status in (ready, warning, duplicate) that have a
        transfer_match or operation_type='transfer'.
        """
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row_status == "committed":
            raise ImportValidationError("Импортированную строку нельзя разорвать.")

        nd: dict = dict(row.normalized_data_json or {})
        nd.pop("transfer_match", None)
        nd.pop("target_account_id", None)
        nd.pop("operation_type", None)
        nd.pop("was_orphan_transfer", None)
        nd["transfer_match_locked"] = True  # prevent matcher from re-pairing immediately
        row.normalized_data_json = nd
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
        """Single-row edit — delegated to ImportRowEditor (extracted 2026-04-29
        as §1 backlog step 7). Translates the editor's local exception types
        back to ImportService's public names so callers stay unchanged.
        """
        from app.services.import_row_editor import (
            ImportNotFoundError as _RENotFound,
            ImportRowEditor,
            ImportValidationError as _REValidation,
        )
        editor = ImportRowEditor(
            self.db,
            import_repo=self.import_repo,
            recalculate_summary_fn=self._recalculate_summary,
            serialize_row_fn=self._serialize_preview_row,
        )
        try:
            return editor.update_row(user_id=user_id, row_id=row_id, payload=payload)
        except _RENotFound as exc:
            raise ImportNotFoundError(str(exc)) from exc
        except _REValidation as exc:
            raise ImportValidationError(str(exc)) from exc

    def _validate_manual_row(
        self, *, normalized: dict[str, Any], current_status: str, issues: list[str],
        allow_ready_status: bool = True,
    ) -> tuple[str, list[str]]:
        """Backward-compat wrapper for tests / callers that still reach into
        the private API. Delegates to ImportRowEditor.validate_manual_row.
        """
        from app.services.import_row_editor import ImportRowEditor
        editor = ImportRowEditor(
            self.db,
            import_repo=self.import_repo,
            recalculate_summary_fn=self._recalculate_summary,
            serialize_row_fn=self._serialize_preview_row,
        )
        return editor.validate_manual_row(
            normalized=normalized,
            current_status=current_status,
            issues=issues,
            allow_ready_status=allow_ready_status,
        )

    @staticmethod
    def _gate_transfer_integrity(
        *,
        normalized: dict[str, Any],
        current_status: str,
        issues: list[str],
        final: bool = False,
    ) -> tuple[str, list[str]]:
        """Delegate to ImportPostProcessor.gate_transfer_integrity.

        Wrapper kept for backward compat — extracted into ImportPostProcessor
        2026-04-29 (§1 backlog step 5).
        """
        from app.services.import_post_processor import ImportPostProcessor
        return ImportPostProcessor.gate_transfer_integrity(
            normalized=normalized,
            current_status=current_status,
            issues=issues,
            final=final,
        )

    def _build_summary_from_rows(self, rows: list[ImportRow]) -> dict[str, int]:
        summary = {
            "total_rows": len(rows),
            "ready_rows": 0,
            "warning_rows": 0,
            "error_rows": 0,
            "duplicate_rows": 0,
            "skipped_rows": 0,
            "parked_rows": 0,
            "user_touched_rows": 0,
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
            nd = row.normalized_data_json or {}
            if nd.get("user_confirmed_at") or nd.get("cluster_bulk_acked_at"):
                summary["user_touched_rows"] += 1
        return summary

    def _apply_refund_matches(self, *, session_id: int) -> None:
        """Delegate to ImportPostProcessor.apply_refund_matches (§1 backlog step 5)."""
        from app.services.import_post_processor import ImportPostProcessor
        ImportPostProcessor(self.db, import_repo=self.import_repo).apply_refund_matches(
            session_id=session_id,
        )

    def _apply_refund_cluster_overrides(self, *, session: ImportSession) -> None:
        """Delegate to ImportPostProcessor.apply_refund_cluster_overrides (§1 backlog step 5)."""
        from app.services.import_post_processor import ImportPostProcessor
        ImportPostProcessor(self.db, import_repo=self.import_repo).apply_refund_cluster_overrides(
            session=session,
        )

    def _apply_bank_mechanics(self, *, session: ImportSession) -> None:
        """Delegate to ImportPostProcessor.apply_bank_mechanics (§9.10 / §6.9)."""
        from app.services.import_post_processor import ImportPostProcessor
        ImportPostProcessor(self.db, import_repo=self.import_repo).apply_bank_mechanics(
            session=session,
        )

    def _reapply_bank_mechanics_for_siblings(
        self, *, user_id: int, exclude_session_id: int
    ) -> None:
        """Re-run bank mechanics for all other preview_ready sessions of this user.

        Called when a new contract_number is saved to an Account during build_preview.
        Sibling sessions may have stale 'regular' rows that failed to resolve the
        counter-account (because the contract wasn't available at their preview time).
        Re-running is idempotent: rows with user_confirmed_at or committed status
        are protected by guards inside ImportPostProcessor.apply_bank_mechanics.
        """
        siblings = (
            self.db.query(ImportSession)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status == "preview_ready",
                ImportSession.id != exclude_session_id,
            )
            .all()
        )
        for sibling in siblings:
            try:
                self._apply_bank_mechanics(session=sibling)
                self.db.commit()
            except Exception:
                self.db.rollback()

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

    def get_queue_preview(self, *, user_id: int) -> dict[str, Any]:
        """Aggregate all parsed rows from the user's active (non-committed)
        sessions into one moderation payload — the unified queue (v1.23).

        Sessions in earlier states (queued / parsing / awaiting_account, or
        with no `account_id` assigned yet) are skipped: their rows aren't
        moderation-ready. The only sessions admitted are
        `status='preview_ready'` AND `account_id IS NOT NULL` — i.e. the
        user has assigned a bank account and clicked «Начать разбор».

        Each row is enriched with source metadata (`session_id`,
        `account_id`, `account_name`, `bank_code`) so the unified UI can
        render a bank pill and apply per-account / per-bank filters
        without an extra round-trip per row.
        """
        sessions = self.import_repo.list_active_sessions(user_id=user_id)
        eligible = [
            s for s in sessions
            if str(s.status or "") == "preview_ready" and s.account_id is not None
        ]

        sessions_payload: list[dict[str, Any]] = []
        rows_payload: list[dict[str, Any]] = []
        all_rows: list[ImportRow] = []

        # Account lookups cached per session — a typical user has 5-10
        # accounts but uploads many sessions over time. Avoid N+1.
        account_cache: dict[int, Any] = {}

        for session in eligible:
            account = None
            if session.account_id is not None:
                account = account_cache.get(session.account_id)
                if account is None:
                    account = self.account_repo.get_by_id_and_user(
                        session.account_id, user_id,
                    )
                    if account is not None:
                        account_cache[session.account_id] = account
            bank_code = (
                (account.bank.code if account is not None and account.bank else None)
                or (session.parse_settings or {}).get("detection", {}).get("bank_code")
            )
            sessions_payload.append({
                "session_id": session.id,
                "filename": session.filename,
                "status": session.status,
                "account_id": session.account_id,
                "account_name": account.name if account else None,
                "bank_code": bank_code,
            })

            rows = self.import_repo.get_rows(session_id=session.id)
            all_rows.extend(rows)
            for row in rows:
                serialized = self._serialize_preview_row(row)
                serialized["session_id"] = session.id
                serialized["account_id"] = session.account_id
                serialized["account_name"] = account.name if account else None
                serialized["bank_code"] = bank_code
                rows_payload.append(serialized)

        return {
            "sessions": sessions_payload,
            "rows": rows_payload,
            "summary": self._build_summary_from_rows(all_rows),
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
            raise ImportValidationError('Не удалось восстановить данные сессии импорта.')

        current_mapping = session.mapping_json or {}
        table_name = payload.table_name or current_mapping.get("selected_table") or tables[0].name
        table = next((item for item in tables if item.name == table_name), None)
        if table is None:
            raise ImportValidationError('Выбранная таблица не найдена в источнике.')
        if not table.rows:
            raise ImportValidationError('В выбранной таблице нет строк для импорта.')
        if table.meta.get("schema") == "diagnostics":
            raise ImportValidationError(
                'Структура этого PDF не распознана автоматически. Проверь диагностическую таблицу в результате извлечения и пришли файл для расширения шаблонов.'
            )

        # Store bank_code in mapping_json so downstream services (build_clusters)
        # can read it without re-fetching the account from DB.
        bank_code = account.bank.code if (account.bank is not None) else None
        current_mapping = {**current_mapping, "bank_code": bank_code}

        # Persist account_id on the session so commit_import can later save
        # the extracted contract_number / statement_account_number back to the
        # account. Without this, the account is always NULL at commit time.
        if session.account_id != payload.account_id:
            session.account_id = payload.account_id
            self.db.add(session)

        # Early write: save contract_number / statement_account_number to the
        # Account as soon as build_preview runs (not only at commit). This lets
        # other sessions (e.g. Яндекс Дебет) find this account via
        # AccountRepository.find_by_contract_number without requiring a specific
        # import order. Guard: only write if the field is currently empty.
        _ps = session.parse_settings or {}
        _early_updates: dict[str, str] = {}
        if _ps.get("contract_number") and not account.contract_number:
            _early_updates["contract_number"] = _ps["contract_number"]
        if _ps.get("statement_account_number") and not account.statement_account_number:
            _early_updates["statement_account_number"] = _ps["statement_account_number"]
        if _early_updates:
            self.account_repo.update(account, auto_commit=False, **_early_updates)

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

        # Per-row Phase 1-4 logic lives in PreviewRowProcessor (extracted
        # 2026-04-29 as §1 backlog step 8). The processor is stateless and
        # reusable across rows — instantiated once outside the loop.
        # Brand resolver caches active patterns once per call, then matches
        # ~one row per substring sweep — see brand_resolver_service.
        from app.services.brand_resolver_service import BrandResolverService
        from app.services.preview_row_processor import PreviewRowProcessor
        row_processor = PreviewRowProcessor(
            self.db,
            category_rule_repo=self.category_rule_repo,
            enrichment=self.enrichment,
            find_duplicate_fn=self._find_duplicate,
            alias_service=self._alias_service,
            brand_resolver=BrandResolverService(self.db),
        )
        bank_for_normalize = bank_code or str(getattr(session, "source_type", None) or "unknown")

        for index, raw_row in enumerate(table.rows, start=1):
            processed = row_processor.process(
                raw_row=raw_row,
                row_index=index,
                user_id=user_id,
                session_account_id=payload.account_id,
                bank_code=bank_code,
                bank_for_normalize=bank_for_normalize,
                field_mapping=payload.field_mapping,
                date_format=payload.date_format,
                default_currency=effective_currency,
                skip_duplicates=payload.skip_duplicates,
                accounts_cache=_accounts_cache,
                categories_cache=_categories_cache,
                history_sample_cache=_history_cache,
            )
            normalized = processed.normalized
            status = processed.status
            issues = processed.issues
            unresolved_fields = processed.unresolved_fields
            error_message = processed.error_message
            duplicate = processed.duplicate

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
        # services (build_clusters) can access them without re-fetching the account from DB.
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

        # Early save of contract token from row descriptions → Account.contract_number.
        # Complements the parse_settings early save above: for banks whose PDF headers
        # don't carry the contract number (e.g. Ozon Bank), the contract appears only
        # in transaction descriptions. Extracting it here ensures find_by_contract_number
        # can resolve the sibling account via Level 1 (Account field) regardless of
        # which session is previewed first, making the matching fully order-independent.
        _new_contract_saved = False
        if not account.contract_number:
            _row_contracts = [
                str((r.normalized_data_json or {}).get("tokens", {}).get("contract") or "")
                for r in preview_rows
                if (r.normalized_data_json or {}).get("tokens", {}).get("contract")
            ]
            if _row_contracts:
                from collections import Counter as _Counter
                _dominant = _Counter(_row_contracts).most_common(1)[0][0]
                self.account_repo.update(account, auto_commit=False, contract_number=_dominant)
                _new_contract_saved = True

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

        # Bank-mechanics post-process (§9.10 / §6.9): propagate cluster-level
        # bank_mechanics results to individual rows. Two effects:
        # (1) suggest_exclude=True → auto-exclude Яндекс Сплит phantom-mirror
        #     rows («погашение основного долга» income) so the Сплит balance
        #     is not double-credited at commit time.
        # (2) resolved_target_account_id → stamp target_account_id on Яндекс
        #     Дебет transfer rows (resolved from the contract token in the
        #     cluster's identifier) so the user does not have to pick the
        #     counter-account manually.
        self._apply_bank_mechanics(session=session)
        self.db.commit()

        # If a new contract was saved to Account during this preview, sibling
        # sessions may have stale 'regular' rows that couldn't resolve the
        # counter-account before the contract was available. Re-run bank mechanics
        # for all other preview_ready sessions of this user so they benefit
        # immediately — no manual re-open required.
        if _new_contract_saved:
            self._reapply_bank_mechanics_for_siblings(user_id=user_id, exclude_session_id=session.id)


        # Safety gate: post-processors change operation_type without
        # re-running the preview status checks. A refund or regular row
        # without a category must never be ready — enforce the invariant
        # here, after all post-processors have had their turn.
        _needs_fix = [
            row for row in self.import_repo.list_rows(session_id=session.id)
            if row.status == "ready"
            and str((row.normalized_data_json or {}).get("operation_type") or "").lower()
               in ("regular", "refund")
            and not (row.normalized_data_json or {}).get("category_id")
        ]
        if _needs_fix:
            for _row in _needs_fix:
                _row.status = "warning"
                self.db.add(_row)
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
            raise ImportNotFoundError('Строка импорта не найдена.')

        _, row = session_row
        normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))

        norm_desc = normalized.get("normalized_description")
        orig_desc = normalized.get("import_original_description") or normalized.get("description")
        category_id = normalized.get("category_id")
        operation_type = normalized.get("operation_type") or "regular"

        if not norm_desc:
            raise ImportValidationError('Строка не содержит нормализованного описания для создания правила.')
        if not category_id:
            raise ImportValidationError('Строка не содержит категории для создания правила.')
        if operation_type in NON_ANALYTICS_OPERATION_TYPES:
            raise ImportValidationError('Для данного типа операции правило классификации не применяется.')

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

        Per-row decision tree delegated to CommitOrchestrator (extracted
        2026-04-29 as §1 backlog step 6). This method retains:
          • session lookup + `SELECT FOR UPDATE` lock
          • per-session summary recalculation
          • account-level metadata writes (contract_number / statement_account_number)
          • final session.status flip ('committed' vs 'preview_ready')
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
            raise ImportValidationError("Нет подготовленных строк для импорта.")

        from app.services.commit_orchestrator import CommitOrchestrator
        orchestrator = CommitOrchestrator(
            self.db,
            import_repo=self.import_repo,
            category_rule_repo=self.category_rule_repo,
            transaction_service=self.transaction_service,
            transfer_linker=self.transfer_linker,
            counterparty_fp_service=self._counterparty_fp_service,
            prepare_payloads_fn=self._prepare_transaction_payloads,
        )
        counters = orchestrator.commit_rows(user_id=user_id, rows=import_rows)
        imported_count = counters.imported
        skipped_count = counters.skipped
        duplicate_count = counters.duplicate
        error_count = counters.error
        review_count = counters.review
        parked_count = counters.parked

        # ─── per-row decision tree lives in CommitOrchestrator now ───
        # Everything below here is session-level finalization.
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

    def commit_queue_confirmed(self, *, user_id: int) -> dict[str, Any]:
        """Atomic multi-session commit of all confirmed/ready rows (v1.23).

        Runs the per-row CommitOrchestrator over every preview-ready
        session of the user, then finalizes each session (auto-close when
        empty, recalc summary, sweep account metadata). Issues ONE
        `db.commit()` at the end — either every eligible row commits or
        nothing does (modulo per-row exceptions caught by the orchestrator,
        which keep counters but don't abort the batch).

        Eligibility filter mirrors `get_queue_preview` and
        `get_queue_bulk_clusters`: `status='preview_ready'` AND
        `account_id IS NOT NULL`. Same row-commit semantics as the
        per-session `commit_import` (ready rows always go; warning rows
        only with user_confirmed_at / cluster_bulk_acked_at) — variant C
        of the spec.

        Returns aggregated totals plus per-session breakdown so the UI
        can show «Импортировано N транзакций из M выписок».
        """
        sessions = self.import_repo.list_active_sessions(user_id=user_id)
        eligible = [
            s for s in sessions
            if str(s.status or "") == "preview_ready" and s.account_id is not None
        ]
        empty_totals = {
            "imported": 0, "skipped": 0, "duplicate": 0,
            "error": 0, "review": 0, "parked": 0,
        }
        if not eligible:
            return {"sessions": [], "totals": empty_totals}

        # Lock every eligible session to serialize concurrent commits
        # (e.g. rapid double-click on «Импортировать»). `with_for_update()`
        # is dialect-aware: on PostgreSQL it emits `FOR UPDATE`, on SQLite
        # (test harness) it's a silent no-op.
        eligible_ids = [s.id for s in eligible]
        (
            self.db.query(ImportSession)
            .filter(ImportSession.id.in_(eligible_ids))
            .with_for_update()
            .all()
        )

        from app.services.commit_orchestrator import CommitOrchestrator
        orchestrator = CommitOrchestrator(
            self.db,
            import_repo=self.import_repo,
            category_rule_repo=self.category_rule_repo,
            transaction_service=self.transaction_service,
            transfer_linker=self.transfer_linker,
            counterparty_fp_service=self._counterparty_fp_service,
            prepare_payloads_fn=self._prepare_transaction_payloads,
        )

        per_session: list[dict[str, Any]] = []
        totals = dict(empty_totals)

        for session in eligible:
            import_rows = self.import_repo.get_rows(session_id=session.id)
            if not import_rows:
                continue
            counters = orchestrator.commit_rows(user_id=user_id, rows=import_rows)
            totals["imported"] += counters.imported
            totals["skipped"] += counters.skipped
            totals["duplicate"] += counters.duplicate
            totals["error"] += counters.error
            totals["review"] += counters.review
            totals["parked"] += counters.parked

            # Session-level finalize — same logic as `commit_import`.
            remaining_rows = [
                row
                for row in self.import_repo.get_rows(session_id=session.id)
                if (
                    row.created_transaction_id is None
                    and str(row.status or "").strip().lower() != "committed"
                )
            ]
            remaining_summary = self._build_summary_from_rows(remaining_rows)
            session.status = "committed" if not remaining_rows else "preview_ready"
            session.summary_json = {
                **(session.summary_json or {}),
                **remaining_summary,
                "imported_count": counters.imported,
                "skipped_count": counters.skipped,
                "duplicate_count": counters.duplicate,
                "error_count": counters.error,
                "review_count": counters.review,
                "parked_count": counters.parked,
            }
            # Account metadata sweep (contract / statement number) — only
            # propagates when the account doesn't already have those values.
            parse_settings = session.parse_settings or {}
            contract_number = parse_settings.get("contract_number")
            statement_account_number = parse_settings.get("statement_account_number")
            if session.account_id and (contract_number or statement_account_number):
                account = self.account_repo.get_by_id_and_user(
                    session.account_id, user_id,
                )
                updates: dict[str, Any] = {}
                if account and contract_number and not account.contract_number:
                    updates["contract_number"] = contract_number
                if (
                    account and statement_account_number
                    and not account.statement_account_number
                ):
                    updates["statement_account_number"] = statement_account_number
                if account and updates:
                    self.account_repo.update(
                        account, auto_commit=False, **updates,
                    )
            self.db.add(session)

            per_session.append({
                "session_id": session.id,
                "status": session.status,
                "imported": counters.imported,
                "skipped": counters.skipped,
                "duplicate": counters.duplicate,
                "error": counters.error,
                "review": counters.review,
                "parked": counters.parked,
            })

        # ONE commit covers every session's row inserts + every session
        # status flip. Multi-session atomicity in the spirit of variant C.
        self.db.commit()

        return {
            "sessions": per_session,
            "totals": totals,
        }

    # Transfer create/link delegated to TransferLinkingService. These thin
    # wrappers keep `self._...` call sites working and translate the service's
    # `TransferLinkingError` into the public `ImportValidationError` so caller
    # exception handling stays unchanged.
    def _link_transfer_to_committed_pair(
        self, *, user_id: int, payload: dict[str, Any], committed_tx_id: int,
    ) -> TransactionModel | None:
        from app.services.transfer_linking_service import TransferLinkingError
        try:
            return self.transfer_linker.link_to_committed_orphan(
                user_id=user_id, payload=payload, committed_tx_id=committed_tx_id,
            )
        except TransferLinkingError as exc:
            raise ImportValidationError(str(exc)) from exc

    def _link_transfer_to_committed_cross_session_pair(
        self, *, user_id: int, payload: dict[str, Any], matched_import_row_id: int,
    ) -> TransactionModel | None:
        return self.transfer_linker.link_to_committed_cross_session_phantom(
            user_id=user_id, payload=payload, matched_import_row_id=matched_import_row_id,
        )

    def _create_transfer_pair(
        self, *, user_id: int, payload: dict[str, Any],
    ) -> tuple[TransactionModel, TransactionModel]:
        from app.services.transfer_linking_service import TransferLinkingError
        try:
            return self.transfer_linker.create_transfer_pair(
                user_id=user_id, payload=payload,
            )
        except TransferLinkingError as exc:
            raise ImportValidationError(str(exc)) from exc

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
            raise ValueError('Не указан счёт для транзакции.')
        if amount in (None, ""):
            raise ValueError('Не указана сумма транзакции.')
        if not currency:
            raise ValueError('Не указана валюта транзакции.')
        if not tx_type:
            raise ValueError('Не указан тип транзакции.')
        if not operation_type:
            raise ValueError('Не указан operation_type транзакции.')

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
            # Spec §13 (v1.20): denormalize fingerprint onto Transaction so the
            # history-based orphan-transfer hint can do an indexed lookup
            # without joining through ImportRow.
            "fingerprint": (normalized.get("fingerprint") or None),
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
                raise ValueError('Пустое значение суммы.')
            return Decimal(cleaned)
        raise TypeError('Некорректный формат суммы.')

    @staticmethod
    def _to_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise TypeError('Некорректный формат даты транзакции.')

    def _session_to_upload_response(
        self,
        session: ImportSession,
        *,
        action_required: DuplicateAction | None = None,
        existing_progress: ExistingProgress | None = None,
        existing_status: str | None = None,
        existing_created_at: datetime | None = None,
    ) -> dict[str, Any]:
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
            # Этап 0.5 — duplicate-detection signals. All None on a fresh upload.
            "action_required": action_required,
            "existing_progress": existing_progress,
            "existing_status": existing_status,
            "existing_created_at": existing_created_at,
        }

    def _count_existing_progress(self, session_id: int) -> ExistingProgress:
        """Project `ImportRepository.count_session_progress` into the schema type.

        The aggregation lives in the repository (proper layer for SQL); this
        thin wrapper exists so the upload flow doesn't have to know dict-key
        names or rebuild the Pydantic model. Field rename
        `user_actions_count` → `user_actions` is intentional — the schema
        contract uses the shorter name in the JSON payload.
        """
        counts = self.import_repo.count_session_progress(session_id=session_id)
        return ExistingProgress(
            committed_rows=counts["committed_rows"],
            user_actions=counts["user_actions_count"],
            total_rows=counts["total_rows"],
        )

    def _duplicate_choose_response(
        self, action: DuplicateAction, session: ImportSession,
    ) -> dict[str, Any]:
        """Fields to overlay on `_session_to_upload_response` for an active
        duplicate (`action_required="choose"`). Computes the progress snapshot
        once so the UI's [Перезаписать] button can show 'в существующей: 47
        действий, 12 закоммиченных' without an extra round-trip.
        """
        return {
            "action_required": action,
            "existing_progress": self._count_existing_progress(session.id),
            "existing_status": session.status,
            "existing_created_at": session.created_at,
        }

    def _duplicate_warn_response(
        self, session: ImportSession,
    ) -> dict[str, Any]:
        """Response shape for `action_required="warn"` — only existing match
        is COMMITTED. There's no active session to "open"; the UI shows a soft
        "уже импортирована N дней назад" banner with [Загрузить как новую] /
        [Отмена]. `session_id` points at the committed session so the UI can
        deep-link to its history if needed.
        """
        return {
            "session_id": session.id,
            "filename": session.filename,
            "source_type": session.source_type,
            "status": session.status,
            "detected_columns": [],
            "sample_rows": [],
            "total_rows": 0,
            "extraction": {},
            "detection": {},
            "suggested_account_id": session.account_id,
            "contract_number": None,
            "contract_match_reason": None,
            "contract_match_confidence": None,
            "statement_account_number": None,
            "statement_account_match_reason": None,
            "statement_account_match_confidence": None,
            "action_required": DuplicateAction.WARN,
            "existing_progress": None,
            "existing_status": session.status,
            "existing_created_at": session.created_at,
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
        contract: str | None = None,
    ) -> bool:
        """§8.1 deduplication against committed transactions.

        Primary discriminant is **skeleton** — the v2 normalizer's
        placeholder-rich form, which collapses identifier variation (same
        merchant, different phone/contract) into one key. This is what the
        spec calls for.

        Exception: when `contract` is provided (transfer rows with a contract
        number in the description), skeleton candidates are post-filtered to
        require the same contract value. "Внутрибанковский перевод с договора
        5867986654" and "…договора 5452737298" produce identical skeletons but
        are transfers between different accounts — they must not be merged.

        The function is layered:
          1. (account + amount + date ±1 + skeleton) — strict match. Bank
             timezone drift can shift `transaction_date` by a day, so we
             accept ±1 day here. No description filter — user may have
             renamed the original transaction.
          2. Fallback for pre-0052 transactions whose skeleton is NULL:
             widen to ±3 days and match on `normalized_description`. Legacy
             rows keep working until the backfill script populates skeleton.
        """
        from app.services.import_normalizer_v2 import extract_tokens as _extract_tokens

        incoming_skeleton = (skeleton or "").strip()
        incoming_norm = (normalized_description or "").strip().lower()

        def _contract_matches(candidate: Any) -> bool:
            """Return True when the candidate is compatible with `contract`."""
            if not contract:
                return True
            candidate_contract = _extract_tokens(
                candidate.description or ""
            ).contract
            return candidate_contract == contract

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
            if any(_contract_matches(c) for c in exact_candidates):
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
            if any(_contract_matches(c) for c in wide_candidates):
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
            and _contract_matches(item)
            for item in legacy_candidates
        )

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
