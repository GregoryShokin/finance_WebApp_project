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
from app.services.import_confidence import ImportConfidenceService
from app.services.import_extractors import ExtractionResult, ImportExtractorRegistry
from app.schemas.import_normalized import NormalizedDataV2
from app.services.import_normalizer import ImportNormalizer
from app.services.import_normalizer_v2 import (
    extract_tokens as v2_extract_tokens,
    fingerprint as v2_fingerprint,
    normalize_skeleton as v2_normalize_skeleton,
)
from app.services.import_recognition_service import ImportRecognitionService
from app.services.import_validator import ImportRowValidationError
from app.services.transaction_enrichment_service import (
    ALLOWED_OPERATION_TYPES,
    TransactionEnrichmentService,
)
from app.services.transaction_service import NON_ANALYTICS_OPERATION_TYPES, TransactionService, TransactionValidationError
from app.services.transfer_matcher_service import TransferMatcherService


logger = logging.getLogger(__name__)

RAW_TYPE_TO_OPERATION_TYPE = {
    "purchase": "regular",
    "transfer": "transfer",
    "investment_buy": "investment_buy",
    "investment_sell": "investment_sell",
    "credit_disbursement": "credit_disbursement",
    "credit_payment": "credit_payment",
    "credit_interest": "regular",
}


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

    def list_active_sessions(self, *, user_id: int) -> dict[str, Any]:
        sessions = self.import_repo.list_active_sessions(user_id=user_id)
        items = []
        for session in sessions:
            rows = self.import_repo.list_rows(session_id=session.id)
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


    def update_row(self, *, user_id: int, row_id: int, payload: ImportRowUpdateRequest) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("РЎС‚СЂРѕРєР° РёРјРїРѕСЂС‚Р° РЅРµ РЅР°Р№РґРµРЅР°.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("РРјРїРѕСЂС‚РёСЂРѕРІР°РЅРЅСѓСЋ СЃС‚СЂРѕРєСѓ РЅРµР»СЊР·СЏ РёР·РјРµРЅРёС‚СЊ.")

        normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))

        for field in ("account_id", "target_account_id", "credit_account_id", "category_id", "counterparty_id", "amount", "type", "operation_type", "debt_direction", "description", "currency", "credit_principal_amount", "credit_interest_amount"):
            value = getattr(payload, field)
            if value is not None:
                normalized[field] = value

        if payload.split_items is not None:
            normalized["split_items"] = [
                {
                    "category_id": item.category_id,
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

    def _validate_manual_row(self, *, normalized: dict[str, Any], current_status: str, issues: list[str], allow_ready_status: bool = True) -> tuple[str, list[str]]:
        status = current_status
        local_issues = [item for item in issues if item]

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

        if account_id in (None, "", 0):
            local_issues.append("РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚.")
            status = "warning"

        amount_decimal = None
        try:
            if amount not in (None, ""):
                amount_decimal = self._to_decimal(amount)
        except (ValueError, TypeError, InvalidOperation):
            local_issues.append("РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ СЃСѓРјРјР°.")
            status = "error"

        if operation_type == "transfer":
            target_account_id = normalized.get("target_account_id")
            tx_type = str(normalized.get("type") or "expense")
            normalized["credit_account_id"] = None
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            if target_account_id in (None, "", 0):
                # For income transfers, target = source account; for expense, target = destination.
                missing_msg = "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РѕС‚РїСЂР°РІРёС‚РµР»СЏ." if tx_type == "income" else "РќРµ СѓРєР°Р·Р°РЅ СЃС‡С‘С‚ РїРѕСЃС‚СѓРїР»РµРЅРёСЏ."
                local_issues.append(missing_msg)
                status = "warning"
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
        elif operation_type == "credit_payment":
            credit_account_id = normalized.get("credit_account_id") or normalized.get("target_account_id")
            normalized["category_id"] = None
            normalized["split_items"] = []
            normalized["target_account_id"] = credit_account_id
            normalized["credit_account_id"] = credit_account_id
            if credit_account_id in (None, "", 0):
                local_issues.append("РќРµ РІС‹Р±СЂР°РЅ РєСЂРµРґРёС‚РЅС‹Р№ СЃС‡С‘С‚.")
                status = "warning"

            principal_raw = normalized.get("credit_principal_amount")
            interest_raw = normalized.get("credit_interest_amount")
            principal_amount = None
            interest_amount = None

            if principal_raw in (None, ""):
                local_issues.append("Р”Р»СЏ РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РѕСЃРЅРѕРІРЅРѕР№ РґРѕР»Рі.")
                status = "warning"
            else:
                try:
                    principal_amount = self._to_decimal(principal_raw)
                except (ValueError, TypeError, InvalidOperation):
                    local_issues.append("РќРµРєРѕСЂСЂРµРєС‚РЅР°СЏ СЃСѓРјРјР°.")
                    status = "error"

            if interest_raw in (None, ""):
                local_issues.append("Р”Р»СЏ РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РїСЂРѕС†РµРЅС‚С‹.")
                status = "warning"
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
                valid_split = True
                split_total = Decimal("0")
                cleaned_split_items: list[dict[str, Any]] = []
                for item in split_items:
                    category_id = item.get("category_id") if isinstance(item, dict) else None
                    raw_amount = item.get("amount") if isinstance(item, dict) else None
                    description = item.get("description") if isinstance(item, dict) else None
                    if category_id in (None, "", 0):
                        valid_split = False
                        local_issues.append("Р’ СЂР°Р·Р±РёРІРєРµ РґР»СЏ РєР°Р¶РґРѕР№ С‡Р°СЃС‚Рё РЅСѓР¶РЅР° РєР°С‚РµРіРѕСЂРёСЏ.")
                        break
                    try:
                        split_amount = self._to_decimal(raw_amount)
                    except (ValueError, TypeError, InvalidOperation):
                        valid_split = False
                        local_issues.append("Р Р°Р·Р±РёРІРєР° Р·Р°РїРѕР»РЅРµРЅР° РЅРµРєРѕСЂСЂРµРєС‚РЅРѕ.")
                        break
                    if split_amount <= 0:
                        valid_split = False
                        local_issues.append("Р’ СЂР°Р·Р±РёРІРєРµ РєР°Р¶РґР°СЏ С‡Р°СЃС‚СЊ РґРѕР»Р¶РЅР° Р±С‹С‚СЊ Р±РѕР»СЊС€Рµ РЅСѓР»СЏ.")
                        break
                    split_total += split_amount
                    cleaned_split_items.append({
                        "category_id": int(category_id),
                        "amount": str(split_amount),
                        "description": description,
                    })

                if valid_split and amount_decimal is not None and split_total != amount_decimal:
                    valid_split = False
                    local_issues.append("РЎСѓРјРјР° СЂР°Р·Р±РёРІРєРё РґРѕР»Р¶РЅР° СЃРѕРІРїР°РґР°С‚СЊ СЃ СЃСѓРјРјРѕР№ С‚СЂР°РЅР·Р°РєС†РёРё.")

                if valid_split and len(cleaned_split_items) >= 2:
                    normalized["split_items"] = cleaned_split_items
                    normalized["category_id"] = None
                else:
                    status = "warning" if status != "error" else status
            else:
                normalized["split_items"] = []
                if normalized.get("category_id") in (None, "", 0):
                    local_issues.append("РќРµ РІС‹Р±СЂР°РЅР° РєР°С‚РµРіРѕСЂРёСЏ.")
                    status = "warning"
        elif operation_type == "refund":
            normalized["target_account_id"] = None
            normalized["split_items"] = []
            if normalized.get("category_id") in (None, "", 0):
                local_issues.append("РќРµ РІС‹Р±СЂР°РЅР° РєР°С‚РµРіРѕСЂРёСЏ.")
                status = "warning"
        else:
            normalized["target_account_id"] = None
            normalized["category_id"] = None
            normalized["split_items"] = []

        if not normalized.get("description"):
            local_issues.append("РџСѓСЃС‚РѕРµ РѕРїРёСЃР°РЅРёРµ РѕРїРµСЂР°С†РёРё.")
            status = "warning"

        if not normalized.get("transaction_date") and not normalized.get("date"):
            local_issues.append("РќРµ СѓРєР°Р·Р°РЅР° РґР°С‚Р° РѕРїРµСЂР°С†РёРё.")
            status = "error"

        unique_issues = list(dict.fromkeys(local_issues))

        if status != "duplicate":
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
        return summary

    def _recalculate_summary(self, session_id: int) -> dict[str, int]:
        rows = self.import_repo.get_rows(session_id=session_id)
        return self._build_summary_from_rows(rows)

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
                normalized["category_id"] = _cat_rule.category_id if _cat_rule else enrichment.get("suggested_category_id")

                normalized["operation_type"] = enrichment.get("suggested_operation_type") or self._resolve_operation_type(normalized)

                # Transfers and non-analytics types don't have categories — clear any
                # rule-matched category that was assigned before operation_type was resolved.
                if str(normalized.get("operation_type") or "") in ("transfer", *NON_ANALYTICS_OPERATION_TYPES):
                    normalized["category_id"] = None
                normalized["type"] = enrichment.get("suggested_type") or normalized.get("direction") or "expense"

                if str(normalized["operation_type"]) == "transfer":
                    # account_id always = session account ("РЎС‡С‘С‚ РёР· РІС‹РїРёСЃРєРё"), regardless of direction.
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
                else:
                    normalized["account_id"] = enrichment.get("suggested_account_id") or payload.account_id
                    normalized["target_account_id"] = enrichment.get("suggested_target_account_id")

                amount_decimal = self._to_decimal(normalized.get("amount"))
                transaction_dt = self._to_datetime(normalized.get("transaction_date") or normalized.get("date"))

                current_operation_type = str(normalized.get("operation_type") or "regular")
                _raw_account_id = normalized.get("account_id")
                if _raw_account_id in (None, "", 0):
                    if current_operation_type == "transfer":
                        issues.append("РќРµ СѓРґР°Р»РѕСЃСЊ РѕРїСЂРµРґРµР»РёС‚СЊ СЃС‡С‘С‚ РёР· РІС‹РїРёСЃРєРё вЂ” СѓРєР°Р¶Рё РІСЂСѓС‡РЅСѓСЋ.")
                        status = "warning"
                    current_account_id = 0
                else:
                    current_account_id = int(_raw_account_id)

                # Transfer-specific deduplication: look for an existing transfer that already
                # involves the session account on either side (same amount, date В±2 days).
                # account_id is always the session account, so we always search by it.
                if current_operation_type == "transfer":
                    # account_id is always the session account (always known).
                    # Search for an existing paired transfer whose other side is the session account.
                    if current_account_id != 0:
                        transfer_pair_tx = self._find_transfer_pair_duplicate(
                            user_id=user_id,
                            account_id=current_account_id,
                            amount=amount_decimal,
                            transaction_date=transaction_dt,
                        )
                        if transfer_pair_tx is not None:
                            status = "duplicate"
                            issues.append("Р’С‚РѕСЂР°СЏ СЃС‚РѕСЂРѕРЅР° СѓР¶Рµ РёРјРїРѕСЂС‚РёСЂРѕРІР°РЅРЅРѕРіРѕ РїРµСЂРµРІРѕРґР°.")
                            # Determine the other side account for the hint.
                            # The existing transaction record: account_id = its own account, target_account_id = other side.
                            if transfer_pair_tx.account_id == current_account_id:
                                other_account_id = transfer_pair_tx.target_account_id
                            else:
                                other_account_id = transfer_pair_tx.account_id
                            other_account = self.account_repo.get_by_id_and_user(other_account_id, user_id) if other_account_id else None
                            normalized["transfer_pair_hint"] = {
                                "date": transfer_pair_tx.transaction_date.date().isoformat(),
                                "source_account_name": other_account.name if other_account else None,
                            }

                duplicate = status != "duplicate" and self._find_duplicate(
                    user_id=user_id,
                    account_id=current_account_id,
                    amount=amount_decimal,
                    transaction_date=transaction_dt,
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

        # Cross-session transfer matching: find pairs across all active sessions
        # for this user and annotate rows with operation_type=transfer + target_account_id.
        self.transfer_matcher.match_transfers_for_user(user_id=user_id)
        self.db.commit()

        # Build response AFTER matcher so the frontend sees updated transfer data.
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

        for row in import_rows:
            row_status = str(row.status or "").strip().lower()

            if row_status == "duplicate":
                duplicate_count += 1
                skipped_count += 1
                continue

            if row_status == "error":
                error_count += 1
                skipped_count += 1
                continue

            if row_status == "warning":
                review_count += 1
                skipped_count += 1
                continue

            if import_ready_only and row_status != "ready":
                skipped_count += 1
                continue

            if row_status not in {"ready"}:
                skipped_count += 1
                continue

            normalized = row.normalized_data or {}

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

                if operation_type == "transfer" and target_account_id not in (None, "", 0):
                    expense_tx, _income_tx = self._create_transfer_pair(
                        user_id=user_id,
                        payload=payloads[0],
                    )
                    last_transaction = expense_tx
                    imported_count += 1
                elif operation_type == "credit_payment":
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
                category_id = normalized.get("category_id")
                norm_desc = normalized.get("normalized_description")
                orig_desc = normalized.get("import_original_description") or normalized.get("description")
                operation_type = normalized.get("operation_type") or "regular"
                if category_id and norm_desc and operation_type not in NON_ANALYTICS_OPERATION_TYPES:
                    self.category_rule_repo.upsert(
                        user_id=user_id,
                        normalized_description=norm_desc,
                        category_id=int(category_id),
                        original_description=orig_desc or None,
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
        }

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
            "transaction_date": ImportService._to_datetime(transaction_date),
            "credit_principal_amount": normalized.get("credit_principal_amount"),
            "credit_interest_amount": normalized.get("credit_interest_amount"),
            "counterparty_id": normalized.get("counterparty_id"),
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


        split_items = normalized.get("split_items") or []
        if str(operation_type) == "regular" and isinstance(split_items, list) and len(split_items) >= 2:
            payloads: list[dict[str, Any]] = []
            for item in split_items:
                if not isinstance(item, dict):
                    raise ValueError("Р Р°Р·Р±РёРІРєР° Р·Р°РїРѕР»РЅРµРЅР° РЅРµРєРѕСЂСЂРµРєС‚РЅРѕ.")
                category_id = item.get("category_id")
                if category_id in (None, "", 0):
                    raise ValueError("Р’ СЂР°Р·Р±РёРІРєРµ РґР»СЏ РєР°Р¶РґРѕР№ С‡Р°СЃС‚Рё РЅСѓР¶РЅР° РєР°С‚РµРіРѕСЂРёСЏ.")
                split_amount = ImportService._to_decimal(item.get("amount"))
                description = (item.get("description") or base_payload["description"] or "")[:1000]
                payloads.append({
                    **base_payload,
                    "category_id": int(category_id),
                    "amount": split_amount,
                    "description": description,
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
        normalized_description: str | None,
        transaction_type: str = "expense",
    ) -> bool:
        # РЈСЂРѕРІРµРЅСЊ 1: СЃС‚СЂРѕРіРѕРµ СЃРѕРІРїР°РґРµРЅРёРµ вЂ” (СЃС‡С‘С‚ + СЃСѓРјРјР° + РґР°С‚Р° В±1 РґРµРЅСЊ).
        # Р‘Р°РЅРєРѕРІСЃРєРёРµ РґР°С‚С‹ РјРѕРіСѓС‚ СЃРґРІРёРіР°С‚СЊСЃСЏ РЅР° СЃСѓС‚РєРё РёР·-Р·Р° TZ. Р•СЃР»Рё С‚СЂРѕР№РєР° СЃРѕРІРїР°Р»Р°,
        # СЃС‡РёС‚Р°РµРј РґСѓР±Р»РµРј Р‘Р•Р— РїСЂРѕРІРµСЂРєРё РѕРїРёСЃР°РЅРёСЏ: РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РјРѕРі РїРµСЂРµРёРјРµРЅРѕРІР°С‚СЊ
        # С‚СЂР°РЅР·Р°РєС†РёСЋ РїРѕСЃР»Рµ РїРµСЂРІРѕРіРѕ РёРјРїРѕСЂС‚Р°, РёР·-Р·Р° С‡РµРіРѕ description РёР·РјРµРЅРёР»СЃСЏ.
        exact_candidates = self.transaction_repo.find_nearby_duplicates(
            user_id=user_id,
            account_id=account_id,
            amount=amount,
            transaction_date=transaction_date,
            days_window=1,
            transaction_type=transaction_type,
        )
        if exact_candidates:
            return True

        # РЈСЂРѕРІРµРЅСЊ 2: СЂР°СЃС€РёСЂРµРЅРЅС‹Р№ РґРёР°РїР°Р·РѕРЅ В±3 РґРЅСЏ вЂ” С‚РѕР»СЊРєРѕ РµСЃР»Рё СЃРѕРІРїР°РґР°РµС‚
        # normalized_description. РќСѓР¶РµРЅ РґР»СЏ СЂРµРґРєРёС… СЃР»СѓС‡Р°РµРІ Р·Р°РґРµСЂР¶РєРё РїСЂРѕРІРµРґРµРЅРёСЏ РїР»Р°С‚РµР¶Р°.
        incoming_norm = (normalized_description or "").strip().lower()
        if not incoming_norm:
            return False

        wide_candidates = self.transaction_repo.find_nearby_duplicates(
            user_id=user_id,
            account_id=account_id,
            amount=amount,
            transaction_date=transaction_date,
            days_window=3,
            transaction_type=transaction_type,
        )
        return any(
            (item.normalized_description or "").strip().lower() == incoming_norm
            for item in wide_candidates
        )

    def _find_transfer_pair_duplicate(
        self,
        *,
        user_id: int,
        account_id: int,
        amount: Decimal,
        transaction_date: datetime,
    ) -> TransactionModel | None:
        """Returns the matching Transfer transaction when an existing transfer already covers
        this account as the receiving side, so the caller can build a UI hint."""
        return self.transaction_repo.find_transfer_pair_candidate(
            user_id=user_id,
            account_id=account_id,
            amount=amount,
            transaction_date=transaction_date,
        )

    @staticmethod
    def _apply_v2_normalization(
        normalized: dict[str, Any],
        session: ImportSession,
        fallback_account_id: int | None,
        row_index: int,
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
            # bank_code does not exist yet (see Phase 2/3 plan). source_type
            # is the closest stable identifier we have; "unknown" guards against
            # null so fingerprint inputs stay deterministic.
            bank = str(getattr(session, "source_type", None) or "unknown")
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
            fp = v2_fingerprint(bank, account_id, direction, skeleton, tokens.contract)

            model = NormalizedDataV2.from_tokens(
                tokens=tokens, skeleton=skeleton, fingerprint=fp,
            )
            return model.merge_into(normalized)
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
