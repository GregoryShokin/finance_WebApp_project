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
    suggested_account_id: int | None = None
    contract_number: str | None = None
    contract_match_reason: str | None = None
    contract_match_confidence: float | None = None
    statement_account_number: str | None = None
    statement_account_match_reason: str | None = None
    statement_account_match_confidence: float | None = None


class ImportMappingRequest(BaseModel):
    account_id: int
    currency: str = Field(default="RUB", min_length=3, max_length=8)
    date_format: str = Field(default="%Y-%m-%d", min_length=2, max_length=32)
    table_name: str | None = None
    field_mapping: dict[str, str | None] = Field(default_factory=dict)
    skip_duplicates: bool = True

    @model_validator(mode="after")
    def validate_required_fields(self):
        # field_mapping имеет смысл только для табличных источников (CSV/XLSX),
        # где user сам выбирает колонки. Для PDF-выписок (Yandex, Ozon, Т-Банк)
        # парсер извлекает поля из текста через regex, и mapping пустой — это
        # нормально. Frontend для PDF может прислать как пустой dict, так и
        # {date: null, description: null, amount: null} — оба случая считаем
        # «mapping не задан» и пропускаем валидацию.
        field_mapping = self.field_mapping or {}
        if not any(field_mapping.values()):
            return self
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
    # Each split part is a self-contained mini-transaction with its own type.
    # operation_type defaults to 'regular' for backwards compat with the old
    # split UI (which only knew about regular splits with a category).
    operation_type: str = "regular"
    category_id: int | None = None       # required for regular / refund / debt
    target_account_id: int | None = None  # required when operation_type='transfer'
    debt_direction: str | None = None    # required when operation_type='debt'
    amount: Decimal
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


class ImportSessionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    source_type: str
    status: str
    account_id: int | None
    created_at: datetime
    updated_at: datetime
    row_count: int
    ready_count: int
    error_count: int
    # Mirrors session.summary_json["auto_preview"]["status"]:
    # pending | running | ready | failed | skipped | null (never attempted).
    auto_preview_status: str | None = None


class ImportSessionListResponse(BaseModel):
    sessions: list[ImportSessionListItem]
    total: int


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


# ---------------------------------------------------------------------------
# Bulk clusters (И-08 Этап 2)
# ---------------------------------------------------------------------------


class BulkFingerprintClusterResponse(BaseModel):
    """Eligible-for-bulk fingerprint cluster exposed to the wizard UI.

    Only the fields the wizard actually reads — the full `Cluster.to_dict()`
    payload is intentionally not echoed here to keep the wire format stable
    as internal fields evolve.
    """

    fingerprint: str
    count: int
    total_amount: Decimal
    direction: str
    skeleton: str
    row_ids: list[int]
    candidate_category_id: int | None
    candidate_rule_id: int | None
    rule_source: str
    confidence: float
    trust_zone: str
    auto_trust: bool
    # Identifier that defines the cluster — phone/contract/card/iban/person_hash
    # for transfer-like rows, else None. Used by the UI to render a concrete
    # header ("Перевод на +79…6612" instead of "… <PHONE>").
    identifier_key: str | None = None
    identifier_value: str | None = None


class BulkBrandClusterResponse(BaseModel):
    brand: str
    direction: str
    count: int
    total_amount: Decimal
    # Members are referenced by fingerprint — the UI joins them back against
    # the flat cluster list to build the expandable card.
    fingerprint_cluster_ids: list[str]


class BulkCounterpartyGroupResponse(BaseModel):
    """Phase 3 — counterparty-centric grouping. Several fingerprint clusters
    bound to the same counterparty collapse under one UI card labelled with
    the counterparty name instead of a merchant skeleton."""

    counterparty_id: int
    counterparty_name: str
    direction: str
    count: int
    total_amount: Decimal
    fingerprint_cluster_ids: list[str]


class BulkClustersResponse(BaseModel):
    session_id: int
    fingerprint_clusters: list[BulkFingerprintClusterResponse]
    brand_clusters: list[BulkBrandClusterResponse]
    counterparty_groups: list[BulkCounterpartyGroupResponse] = []


class BulkClusterRowUpdate(BaseModel):
    """Per-row update inside a bulk-apply batch — mirrors the subset of
    ImportRowUpdateRequest the bulk flow needs. Each row keeps full
    operation-type flexibility (the marketplace case)."""

    row_id: int
    operation_type: str | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    target_account_id: int | None = None
    credit_account_id: int | None = None
    credit_principal_amount: Decimal | None = None
    credit_interest_amount: Decimal | None = None
    debt_direction: str | None = None


class BulkApplyRequest(BaseModel):
    """One moderator action over a cluster.

    `cluster_key` + `cluster_type` identify the cluster the user is confirming
    (either a single fingerprint or a brand group). `updates` lists the rows
    to modify — excluded rows are simply absent from the list.
    """

    cluster_key: str
    cluster_type: str  # "fingerprint" | "brand"
    updates: list[BulkClusterRowUpdate]


class BulkApplyResponse(BaseModel):
    session_id: int
    confirmed_count: int
    skipped_row_ids: list[int]  # already committed — race-condition guard
    rules_affected: int         # rules that had confirms_delta applied
    summary: ImportPreviewSummary


class AttachRowToClusterRequest(BaseModel):
    """Attach an "Требуют внимания" row to a counterparty or existing cluster.

    Two modes (exactly one must be provided):
      * `counterparty_id` — Phase 3 preferred path. Binds the row's fingerprint
        to the given counterparty; future imports with the same skeleton
        group under that counterparty automatically. Copies the
        counterparty's common category (from prior bindings) if known.
      * `target_fingerprint` — legacy path. Creates a FingerprintAlias and
        routes the row to that fingerprint's cluster. Kept for backwards
        compatibility; UI should prefer counterparty_id.

    Atomic: resolves target metadata, creates binding/alias, commits the row
    as a regular Transaction.
    """

    counterparty_id: int | None = None
    target_fingerprint: str | None = None


class AttachRowToClusterResponse(BaseModel):
    row_id: int
    transaction_id: int | None  # None if validation errored and we rolled back
    target_fingerprint: str | None = None
    counterparty_id: int | None = None
    alias_created: bool = False
    binding_created: bool = False
    source_fingerprint: str | None
    summary: ImportPreviewSummary
