from __future__ import annotations

from datetime import datetime
from enum import Enum
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImportSessionStatus(str, Enum):
    uploaded = "uploaded"
    analyzed = "analyzed"
    preview_ready = "preview_ready"
    committed = "committed"
    failed = "failed"


class ImportRowStatus(str, Enum):
    ready = "ready"
    warning = "warning"
    error = "error"
    duplicate = "duplicate"
    skipped = "skipped"
    committed = "committed"


class ImportSourceType(str, Enum):
    csv = "csv"
    xlsx = "xlsx"
    pdf = "pdf"


class ImportTableInfo(BaseModel):
    name: str
    columns: list[str]
    rows: int
    confidence: float


class ImportDetectionResponse(BaseModel):
    selected_table: str | None = None
    available_tables: list[ImportTableInfo] = Field(default_factory=list)
    field_mapping: dict[str, str | None] = Field(default_factory=dict)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    field_reasons: dict[str, str] = Field(default_factory=dict)
    column_analysis: list[dict] = Field(default_factory=list)
    suggested_date_formats: list[str] = Field(default_factory=list)
    overall_confidence: float = 0.0
    confidence_label: str = "low"
    unresolved_fields: list[str] = Field(default_factory=list)


class ImportUploadResponse(BaseModel):
    session_id: int
    filename: str
    source_type: ImportSourceType
    status: ImportSessionStatus
    detected_columns: list[str]
    sample_rows: list[dict[str, str]]
    total_rows: int
    extraction: dict
    detection: ImportDetectionResponse


class ImportMappingRequest(BaseModel):
    account_id: int
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    date_format: str = Field(default="%Y-%m-%d", min_length=2, max_length=32)
    table_name: str | None = None
    field_mapping: dict[str, str | None]
    skip_duplicates: bool = True

    @model_validator(mode="after")
    def validate_required_fields(self):
        field_mapping = self.field_mapping or {}
        if not field_mapping.get("date"):
            raise ValueError("Нужно указать колонку даты.")
        if not field_mapping.get("description"):
            raise ValueError("Нужно указать колонку описания.")
        if not field_mapping.get("amount") and not (field_mapping.get("income") or field_mapping.get("expense")):
            raise ValueError("Нужно указать либо общую сумму, либо колонки дохода и расхода.")
        return self


class ImportPreviewRowResponse(BaseModel):
    id: int
    row_index: int
    status: ImportRowStatus
    confidence: float = 0.0
    confidence_label: str = "low"
    issues: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    error_message: str | None = None
    review_required: bool = False
    raw_data: dict[str, str]
    normalized_data: dict


class ImportPreviewSummary(BaseModel):
    total_rows: int
    ready_rows: int
    warning_rows: int
    error_rows: int
    duplicate_rows: int
    skipped_rows: int


class ImportPreviewResponse(BaseModel):
    session_id: int
    status: ImportSessionStatus
    summary: ImportPreviewSummary
    detection: ImportDetectionResponse
    rows: list[ImportPreviewRowResponse]


class ImportSplitItemRequest(BaseModel):
    category_id: int
    amount: Decimal
    debt_direction: str | None = None
    description: str | None = None


class ImportRowUpdateRequest(BaseModel):
    account_id: int | None = None
    target_account_id: int | None = None
    credit_account_id: int | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    amount: Decimal | None = None
    type: str | None = None
    operation_type: str | None = None
    debt_direction: str | None = None
    description: str | None = None
    transaction_date: datetime | None = None
    currency: str | None = None
    credit_principal_amount: Decimal | None = None
    credit_interest_amount: Decimal | None = None
    split_items: list[ImportSplitItemRequest] | None = None
    action: str | None = None


class ImportRowUpdateResponse(BaseModel):
    session_id: int
    row: ImportPreviewRowResponse
    summary: ImportPreviewSummary


class ImportCommitRequest(BaseModel):
    import_ready_only: bool = True


class ImportCommitResponse(BaseModel):
    session_id: int
    status: ImportSessionStatus
    summary: ImportPreviewSummary
    remaining_rows: list[ImportPreviewRowResponse] = Field(default_factory=list)
    imported_count: int
    skipped_count: int
    duplicate_count: int
    error_count: int
    review_count: int


class ImportReviewQueueItem(BaseModel):
    session_id: int
    session_status: ImportSessionStatus
    filename: str
    source_type: ImportSourceType
    row_id: int
    row_index: int
    status: ImportRowStatus
    error_message: str | None = None
    issues: list[str] = Field(default_factory=list)
    raw_data: dict = Field(default_factory=dict)
    normalized_data: dict = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ImportReviewQueueResponse(BaseModel):
    items: list[ImportReviewQueueItem] = Field(default_factory=list)
    total: int = 0


class ImportRowLabelRequest(BaseModel):
    user_label: str = Field(..., min_length=1, max_length=500)


class ImportRowLabelResponse(BaseModel):
    rule_id: int
    normalized_description: str
    original_description: str | None
    user_label: str | None
    category_id: int


class ImportSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    filename: str
    source_type: ImportSourceType
    status: ImportSessionStatus
    detected_columns: list[str]
    parse_settings: dict
    mapping_json: dict
    summary_json: dict
    account_id: int | None
    currency: str | None
    created_at: datetime
    updated_at: datetime
