from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession


class ImportRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_session(
        self,
        *,
        user_id: int,
        filename: str,
        file_content: str,
        detected_columns: list[str],
        parse_settings: dict,
        source_type: str = "csv",
    ) -> ImportSession:
        session = ImportSession(
            user_id=user_id,
            filename=filename,
            source_type=source_type,
            status="uploaded",
            file_content=file_content,
            detected_columns=self._to_json_safe(detected_columns),
            parse_settings=self._to_json_safe(parse_settings),
            mapping_json={},
            summary_json={},
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get_session(self, *, session_id: int, user_id: int) -> ImportSession | None:
        return (
            self.db.query(ImportSession)
            .filter(ImportSession.id == session_id, ImportSession.user_id == user_id)
            .first()
        )

    def list_active_sessions(self, *, user_id: int) -> list[ImportSession]:
        """
        Возвращает все сессии пользователя со статусом НЕ 'committed',
        отсортированные по дате создания (новые сначала).
        """
        return (
            self.db.query(ImportSession)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
            )
            .order_by(ImportSession.created_at.desc())
            .all()
        )

    def find_active_by_file_hash(self, *, user_id: int, file_hash: str) -> ImportSession | None:
        return (
            self.db.query(ImportSession)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.file_hash == file_hash,
                ImportSession.status != "committed",
            )
            .order_by(ImportSession.created_at.desc())
            .first()
        )

    def delete_session(self, session: ImportSession) -> None:
        self.db.delete(session)
        self.db.flush()

    def update_session(self, session: ImportSession, **updates) -> ImportSession:
        json_fields = {"detected_columns", "parse_settings", "mapping_json", "summary_json"}
        for key, value in updates.items():
            if key in json_fields:
                value = self._to_json_safe(value)
            setattr(session, key, value)
        self.db.add(session)
        self.db.flush()
        return session

    def create_row(
        self,
        *,
        session_id: int,
        row_index: int,
        raw_data: dict,
        normalized_data: dict,
        status: str,
        errors: list[str] | None = None,
        confidence_score: float | None = None,
        duplicate_candidate: bool | None = None,
        review_required: bool | None = None,
    ) -> ImportRow:
        row = ImportRow(
            session_id=session_id,
            row_index=row_index,
            raw_data_json=self._to_json_safe(raw_data or {}),
            normalized_data_json=self._to_json_safe(normalized_data or {}),
            status=status,
            error_message="\n".join([item for item in (errors or []) if item]) or None,
        )
        self._hydrate_row_runtime_fields(
            row,
            errors=errors,
            confidence_score=confidence_score,
            duplicate_candidate=duplicate_candidate,
            review_required=review_required,
        )
        return row

    def replace_rows(
        self,
        *,
        rows: list[ImportRow],
        session_id: int | None = None,
        session: ImportSession | None = None,
    ) -> None:
        resolved_session_id = session_id or (session.id if session is not None else None)
        if resolved_session_id is None:
            raise ValueError("session_id or session is required")

        self.db.query(ImportRow).filter(ImportRow.session_id == resolved_session_id).delete(synchronize_session=False)
        if rows:
            for row in rows:
                row.raw_data_json = self._to_json_safe(row.raw_data_json or {})
                row.normalized_data_json = self._to_json_safe(row.normalized_data_json or {})
            self.db.add_all(rows)
        self.db.flush()

        for row in rows:
            self._hydrate_row_runtime_fields(row)

        if session is not None:
            setattr(session, "rows", rows)

    def list_rows(self, *, session_id: int) -> list[ImportRow]:
        rows = (
            self.db.query(ImportRow)
            .filter(ImportRow.session_id == session_id)
            .order_by(ImportRow.row_index.asc(), ImportRow.id.asc())
            .all()
        )
        for row in rows:
            self._hydrate_row_runtime_fields(row)
        return rows

    def get_rows(self, *, session_id: int) -> list[ImportRow]:
        return self.list_rows(session_id=session_id)

    def get_row_for_user(self, *, row_id: int, user_id: int) -> tuple[ImportSession, ImportRow] | None:
        result = (
            self.db.query(ImportSession, ImportRow)
            .join(ImportRow, ImportRow.session_id == ImportSession.id)
            .filter(ImportSession.user_id == user_id, ImportRow.id == row_id)
            .first()
        )
        if result is None:
            return None
        session, row = result
        self._hydrate_row_runtime_fields(row)
        return session, row

    def list_review_queue(self, *, user_id: int) -> list[tuple[ImportSession, ImportRow]]:
        rows = (
            self.db.query(ImportSession, ImportRow)
            .join(ImportRow, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportRow.status.in_(["warning", "error"]),
                ImportRow.created_transaction_id.is_(None),
            )
            .order_by(ImportSession.updated_at.desc(), ImportRow.row_index.asc(), ImportRow.id.asc())
            .all()
        )
        for _, row in rows:
            self._hydrate_row_runtime_fields(row)
        return rows

    def list_parked_queue(self, *, user_id: int) -> list[tuple[ImportSession, ImportRow]]:
        rows = (
            self.db.query(ImportSession, ImportRow)
            .join(ImportRow, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportRow.status == "parked",
                ImportRow.created_transaction_id.is_(None),
            )
            .order_by(ImportSession.updated_at.desc(), ImportRow.row_index.asc(), ImportRow.id.asc())
            .all()
        )
        for _, row in rows:
            self._hydrate_row_runtime_fields(row)
        return rows

    def get_row_by_transaction_id(self, *, transaction_id: int) -> ImportRow | None:
        row = (
            self.db.query(ImportRow)
            .filter(ImportRow.created_transaction_id == transaction_id)
            .first()
        )
        if row is not None:
            self._hydrate_row_runtime_fields(row)
        return row

    def update_row(self, row: ImportRow, **updates) -> ImportRow:
        alias_map = {
            "raw_data": "raw_data_json",
            "normalized_data": "normalized_data_json",
            "errors": "error_message",
        }
        json_fields = {"raw_data_json", "normalized_data_json"}
        for key, value in updates.items():
            target_key = alias_map.get(key, key)
            if target_key == "error_message" and isinstance(value, list):
                value = "\n".join([item for item in value if item]) or None
            if target_key in json_fields:
                value = self._to_json_safe(value or {})
            setattr(row, target_key, value)
        self._hydrate_row_runtime_fields(row)
        self.db.add(row)
        self.db.flush()
        return row

    @classmethod
    def _to_json_safe(cls, value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {str(key): cls._to_json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._to_json_safe(item) for item in value]
        return value

    @staticmethod
    def _hydrate_row_runtime_fields(
        row: ImportRow,
        *,
        errors: list[str] | None = None,
        confidence_score: float | None = None,
        duplicate_candidate: bool | None = None,
        review_required: bool | None = None,
    ) -> None:
        row.raw_data = row.raw_data_json or {}
        row.normalized_data = row.normalized_data_json or {}

        if errors is None:
            message = row.error_message or ""
            errors = [item.strip() for item in message.splitlines() if item.strip()]
        row.errors = errors

        row.confidence_score = confidence_score if confidence_score is not None else getattr(row, "confidence_score", 0.0)
        row.duplicate_candidate = duplicate_candidate if duplicate_candidate is not None else getattr(row, "duplicate_candidate", False)
        row.review_required = review_required if review_required is not None else getattr(
            row,
            "review_required",
            row.status in {"warning", "error"},
        )
