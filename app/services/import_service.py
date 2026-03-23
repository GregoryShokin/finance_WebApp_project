from __future__ import annotations

import base64
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.account_repository import AccountRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.imports import ImportMappingRequest, ImportPreviewSummary, ImportRowUpdateRequest
from app.services.import_confidence import ImportConfidenceService
from app.services.import_extractors import ExtractionResult, ImportExtractorRegistry
from app.services.import_normalizer import ImportNormalizer
from app.services.import_recognition_service import ImportRecognitionService
from app.services.import_validator import ImportRowValidationError
from app.services.transaction_enrichment_service import (
    ALLOWED_OPERATION_TYPES,
    TransactionEnrichmentService,
)
from app.services.transaction_service import TransactionService, TransactionValidationError

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
            raise ImportValidationError("Не удалось извлечь данные из файла.")

        primary_table = self._pick_primary_table(extraction)
        detection = self.recognition_service.recognize(table=primary_table)

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
        }

        session = self.import_repo.create_session(
            user_id=user_id,
            filename=filename,
            file_content=storage_payload["content"],
            detected_columns=primary_table.columns,
            parse_settings=parse_settings,
            source_type=extension,
        )
        self.import_repo.update_session(
            session,
            status="analyzed",
            mapping_json=detection,
            summary_json={},
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
        }

    def get_session(self, *, user_id: int, session_id: int) -> ImportSession:
        session = self.import_repo.get_session(session_id=session_id, user_id=user_id)
        if session is None:
            raise ImportNotFoundError("Сессия импорта не найдена.")
        return session


    def send_row_to_review(self, *, user_id: int, row_id: int) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Строка уже импортирована и не может быть отправлена на проверку.")
        if row_status == "duplicate":
            raise ImportValidationError("Дубликат нельзя отправить на проверку вручную.")
        if row_status == "error":
            raise ImportValidationError("Строка уже содержит ошибку и будет доступна в проверке автоматически.")
        if row_status != "ready":
            raise ImportValidationError("На проверку можно отправить только строки со статусом 'Готово'.")

        issues = list(dict.fromkeys([*(getattr(row, "errors", None) or []), "Отправлено на проверку вручную."]))
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
            raise ImportNotFoundError("Строка импорта не найдена.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Импортированную строку нельзя изменить.")

        normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))

        for field in ("account_id", "target_account_id", "category_id", "amount", "type", "operation_type", "description", "currency"):
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
        issues = [item for item in (getattr(row, "errors", None) or []) if item and item != "Исключено пользователем."]
        status = row_status if row_status not in {"committed", "duplicate"} else row_status

        if action == "exclude":
            status = "skipped"
            issues = list(dict.fromkeys([*issues, "Исключено пользователем."]))
        else:
            if action == "restore" and row_status == "skipped":
                status = "warning"
            elif action == "confirm":
                status = "ready"

            status, issues = self._validate_manual_row(normalized=normalized, current_status=status, issues=issues)

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

    def _validate_manual_row(self, *, normalized: dict[str, Any], current_status: str, issues: list[str]) -> tuple[str, list[str]]:
        status = current_status
        local_issues = [item for item in issues if item]

        if status == "skipped":
            return status, list(dict.fromkeys(local_issues))

        blocking_messages = {
            "Не указан счёт.",
            "Не указан счёт поступления.",
            "Не выбрана категория.",
            "Разбивка заполнена некорректно.",
            "Сумма разбивки должна совпадать с суммой транзакции.",
            "В разбивке каждая часть должна быть больше нуля.",
            "В разбивке для каждой части нужна категория.",
            "Пустое описание операции.",
            "Не указана дата операции.",
            "Некорректная сумма.",
            "Счёт списания и счёт поступления не должны совпадать.",
        }
        local_issues = [item for item in local_issues if item not in blocking_messages]

        account_id = normalized.get("account_id")
        operation_type = normalized.get("operation_type") or "regular"
        amount = normalized.get("amount")

        if account_id in (None, "", 0):
            local_issues.append("Не указан счёт.")
            status = "warning"

        amount_decimal = None
        try:
            if amount not in (None, ""):
                amount_decimal = self._to_decimal(amount)
        except (ValueError, TypeError, InvalidOperation):
            local_issues.append("Некорректная сумма.")
            status = "error"

        if operation_type == "transfer":
            target_account_id = normalized.get("target_account_id")
            if target_account_id in (None, "", 0):
                local_issues.append("Не указан счёт поступления.")
                status = "warning"
            elif str(target_account_id) == str(account_id):
                local_issues.append("Счёт списания и счёт поступления не должны совпадать.")
                status = "error"
            normalized["category_id"] = None
            normalized["split_items"] = []
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
                        local_issues.append("В разбивке для каждой части нужна категория.")
                        break
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
                    split_total += split_amount
                    cleaned_split_items.append({
                        "category_id": int(category_id),
                        "amount": str(split_amount),
                        "description": description,
                    })

                if valid_split and amount_decimal is not None and split_total != amount_decimal:
                    valid_split = False
                    local_issues.append("Сумма разбивки должна совпадать с суммой транзакции.")

                if valid_split and len(cleaned_split_items) >= 2:
                    normalized["split_items"] = cleaned_split_items
                    normalized["category_id"] = None
                else:
                    status = "warning" if status != "error" else status
            else:
                normalized["split_items"] = []
                if normalized.get("category_id") in (None, "", 0):
                    local_issues.append("Не выбрана категория.")
                    status = "warning"
        elif operation_type == "refund":
            normalized["target_account_id"] = None
            normalized["split_items"] = []
            if normalized.get("category_id") in (None, "", 0):
                local_issues.append("Не выбрана категория.")
                status = "warning"
        else:
            normalized["target_account_id"] = None
            normalized["category_id"] = None
            normalized["split_items"] = []

        if not normalized.get("description"):
            local_issues.append("Пустое описание операции.")
            status = "warning"

        if not normalized.get("transaction_date") and not normalized.get("date"):
            local_issues.append("Не указана дата операции.")
            status = "error"

        unique_issues = list(dict.fromkeys(local_issues))

        if status != "duplicate":
            unresolved = [item for item in unique_issues if item in blocking_messages]
            status = "ready" if not unresolved else status

        return status, unique_issues

    def _recalculate_summary(self, session_id: int) -> dict[str, int]:
        rows = self.import_repo.get_rows(session_id=session_id)
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


    def build_preview(self, *, user_id: int, session_id: int, payload: ImportMappingRequest) -> dict[str, Any]:
        session = self.get_session(user_id=user_id, session_id=session_id)
        account = self.account_repo.get_by_id_and_user(payload.account_id, user_id)
        if account is None:
            raise ImportValidationError("Выбранный счёт не найден.")

        tables = self._load_tables_from_session(session)
        if not tables:
            raise ImportValidationError("Не удалось восстановить данные сессии импорта.")

        current_mapping = session.mapping_json or {}
        table_name = payload.table_name or current_mapping.get("selected_table") or tables[0].name
        table = next((item for item in tables if item.name == table_name), None)
        if table is None:
            raise ImportValidationError("Выбранная таблица не найдена в источнике.")
        if not table.rows:
            raise ImportValidationError("В выбранной таблице нет строк для импорта.")
        if table.meta.get("schema") == "diagnostics":
            raise ImportValidationError(
                "Структура этого PDF не распознана автоматически. Проверь диагностическую таблицу в результате извлечения и пришли файл для расширения шаблонов."
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
                normalized["account_id"] = enrichment.get("suggested_account_id") or payload.account_id
                normalized["target_account_id"] = enrichment.get("suggested_target_account_id")
                normalized["category_id"] = enrichment.get("suggested_category_id")
                normalized["operation_type"] = enrichment.get("suggested_operation_type") or self._resolve_operation_type(normalized)
                normalized["type"] = enrichment.get("suggested_type") or normalized.get("direction") or "expense"

                amount_decimal = self._to_decimal(normalized.get("amount"))
                transaction_dt = self._to_datetime(normalized.get("transaction_date") or normalized.get("date"))

                duplicate = self._find_duplicate(
                    user_id=user_id,
                    account_id=int(normalized["account_id"]),
                    amount=amount_decimal,
                    transaction_date=transaction_dt,
                    description=normalized.get("description"),
                )
                if duplicate and payload.skip_duplicates:
                    status = "duplicate"
                    issues.append("Похоже на уже существующую транзакцию.")
                elif duplicate:
                    status = "warning"
                    issues.append("Возможный дубликат, проверь перед импортом.")

                if enrichment.get("needs_manual_review") and status == "ready":
                    status = "warning"

                issues.extend(enrichment.get("review_reasons") or [])
                issues.extend(enrichment.get("assignment_reasons") or [])

            except (ImportRowValidationError, ImportValidationError, TransactionValidationError, ValueError, TypeError, InvalidOperation) as exc:
                status = "error"
                error_message = str(exc)
                issues.append(str(exc))

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

        response_rows = [self._serialize_preview_row(row) for row in preview_rows]

        self.import_repo.update_session(
            session,
            status="preview_ready",
            mapping_json=merged_detection,
            summary_json=summary,
        )
        self.db.commit()
        self.db.refresh(session)

        return {
            "session_id": session.id,
            "status": session.status,
            "summary": summary,
            "detection": merged_detection,
            "rows": response_rows,
        }

    def commit_import(self, *, user_id: int, session_id: int, import_ready_only: bool = True) -> dict[str, Any]:
        session = self.get_session(user_id=user_id, session_id=session_id)
        import_rows = self.import_repo.get_rows(session_id=session.id)

        if not import_rows:
            raise ImportValidationError("Нет подготовленных строк для импорта.")

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
                continue

            if not payloads:
                skipped_count += 1
                error_count += 1
                row.status = "error"
                row.errors = list(
                    dict.fromkeys(
                        [*(row.errors or []), "Строка не содержит корректных данных для создания транзакции."]
                    )
                )
                continue

            try:
                last_transaction = None
                for payload in payloads:
                    last_transaction = self.transaction_service.create_transaction(
                        user_id=user_id,
                        payload=payload,
                    )
                    imported_count += 1
                row.status = "committed"
                row.created_transaction_id = last_transaction.id if last_transaction is not None else None
            except TransactionValidationError as exc:
                row.status = "error"
                row.errors = list(dict.fromkeys([*(row.errors or []), str(exc)]))
                skipped_count += 1
                error_count += 1

        session.status = "committed"
        session.summary_json = {
            **(session.summary_json or {}),
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "error_count": error_count,
            "review_count": review_count,
        }
        self.db.commit()
        self.db.refresh(session)

        return {
            "session_id": session.id,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "error_count": error_count,
            "review_count": review_count,
        }

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
            raise ValueError("Не указан счёт для транзакции.")
        if amount in (None, ""):
            raise ValueError("Не указана сумма транзакции.")
        if not currency:
            raise ValueError("Не указана валюта транзакции.")
        if not tx_type:
            raise ValueError("Не указан тип транзакции.")
        if not operation_type:
            raise ValueError("Не указан operation_type транзакции.")

        base_payload: dict[str, Any] = {
            "account_id": int(account_id),
            "target_account_id": normalized.get("target_account_id"),
            "category_id": normalized.get("category_id"),
            "amount": ImportService._to_decimal(amount),
            "currency": str(currency).upper(),
            "type": str(tx_type),
            "operation_type": str(operation_type),
            "description": (normalized.get("description") or "")[:1000],
            "transaction_date": ImportService._to_datetime(transaction_date),
            "needs_review": bool(
                normalized.get("needs_review")
                or normalized.get("review_required")
            ),
        }

        if base_payload.get("target_account_id") not in (None, "", 0):
            base_payload["target_account_id"] = int(base_payload["target_account_id"])
        else:
            base_payload["target_account_id"] = None

        if base_payload.get("category_id") not in (None, "", 0):
            base_payload["category_id"] = int(base_payload["category_id"])
        else:
            base_payload["category_id"] = None

        split_items = normalized.get("split_items") or []
        if str(operation_type) == "regular" and isinstance(split_items, list) and len(split_items) >= 2:
            payloads: list[dict[str, Any]] = []
            for item in split_items:
                if not isinstance(item, dict):
                    raise ValueError("Разбивка заполнена некорректно.")
                category_id = item.get("category_id")
                if category_id in (None, "", 0):
                    raise ValueError("В разбивке для каждой части нужна категория.")
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
                raise ValueError("Пустое значение суммы.")
            return Decimal(cleaned)
        raise TypeError("Некорректный формат суммы.")

    @staticmethod
    def _to_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise TypeError("Некорректный формат даты транзакции.")

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
        description: str | None,
    ) -> bool:
        description = (description or "").strip()
        candidates = self.transaction_repo.find_nearby_duplicates(
            user_id=user_id,
            account_id=account_id,
            amount=amount,
            transaction_date=transaction_date,
        )
        return any((item.description or "").strip() == description for item in candidates)

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
