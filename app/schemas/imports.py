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
    # Parked rows — user chose "Отложить" on a row; it stays out of the
    # current import flow until unparked. Stored in DB as "parked" but was
    # missing from this enum, which made every preview response containing
    # a parked row 500 with ResponseValidationError.
    parked = "parked"
    # Excluded rows — auto-excluded by bank_mechanics (e.g. Яндекс Сплит /
    # Озон кредитка phantom-mirror income rows) or manually by the user.
    # Missing from this enum caused every preview containing an excluded row
    # to 500 with ResponseValidationError.
    excluded = "excluded"


class ImportSourceType(str, Enum):
    csv = "csv"
    xlsx = "xlsx"
    pdf = "pdf"


class DuplicateAction(str, Enum):
    """Signal in `ImportUploadResponse` telling the frontend how to react to
    a duplicate-file detection (Этап 0.5).

    `CHOOSE` — uncommitted session with the same file_hash exists. Frontend
        opens a 3-button modal: open existing / upload as new (force_new) / cancel.
    `WARN`   — only committed sessions with this file_hash exist. Frontend
        shows a soft 2-button warning: upload as new / cancel.

    Absence of the field (None) means no duplicate detected — proceed normally.
    """

    CHOOSE = "choose"
    WARN = "warn"


class ExistingProgress(BaseModel):
    """Progress snapshot of a duplicate-detected session, attached to
    `ImportUploadResponse.existing_progress` ONLY when action_required=CHOOSE.
    Lets the user judge "how much work would I lose by uploading as new" via
    the modal sub-text. Counts come from a single FILTER-aggregation query —
    see `ImportService._count_existing_progress`.
    """

    committed_rows: int
    user_actions: int
    total_rows: int


class AccountCandidate(BaseModel):
    """Account that *might* be the destination for this upload (Шаг 2 of
    auto-account-recognition).

    Emitted in `ImportUploadResponse.account_candidates` when the extractor's
    bank/account_type detection matches multiple accounts for the user — the
    UI shows a quick picker instead of falling back to the full queue. Fields
    are the minimal subset needed to render that picker: id + name + bank +
    type, plus closed-state flags for §13 spec compliance.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    bank_id: int
    bank_name: str | None = None
    account_type: str
    is_closed: bool = False
    contract_number: str | None = None
    statement_account_number: str | None = None


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
    # Auto-account-recognition Шаг 2 (2026-05-06). The extractor classifies the
    # PDF into a bank + account-type pair (Шаг 1) and, when contract /
    # statement_account lookups fail, ImportService tries a Level-3 fallback by
    # matching the user's accounts on (bank, account_type). All these fields
    # are populated on the SAME response that already carries
    # contract_match_*/statement_account_match_* — the frontend reads whichever
    # is non-null and offers the corresponding UX (auto-attach / picker /
    # create-account). Missing values default to None / [] / False so the
    # contract is uniform regardless of whether the upload is supported.
    bank_code: str | None = None
    account_type_hint: str | None = None
    suggested_account_match_reason: str | None = None
    suggested_account_match_confidence: float | None = None
    suggested_bank_id: int | None = None
    account_candidates: list[AccountCandidate] = Field(default_factory=list)
    requires_account_creation: bool = False
    # Duplicate-detection signals (Этап 0.5). All None on a fresh upload.
    # `session_id` itself points to the existing session when action_required is set,
    # so the frontend can `setActive(session_id)` on the [Open existing] action.
    action_required: DuplicateAction | None = None
    existing_progress: ExistingProgress | None = None
    existing_status: ImportSessionStatus | None = None
    existing_created_at: datetime | None = None


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
    # All counters default to 0 because ImportSession.summary_json is reused
    # as the source for both freshly uploaded sessions (where only async job
    # status blocks exist: auto_preview, transfer_match) and fully processed
    # ones (where row counts are populated). Requiring the counters caused
    # 500 errors on the upload / session-list endpoint whenever a session
    # was queued but hadn't yet produced a row breakdown. 0 is the correct
    # neutral value — no rows processed yet means no rows in any bucket.
    total_rows: int = 0
    ready_rows: int = 0
    warning_rows: int = 0
    error_rows: int = 0
    duplicate_rows: int = 0
    skipped_rows: int = 0
    # Pydantic v2: ignore extra keys (auto_preview / transfer_match /
    # moderation status blocks) stored alongside counters in summary_json.
    model_config = {"extra": "ignore"}


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
    category_id: int | None = None       # required for regular / refund; optional for debt
    target_account_id: int | None = None  # required when operation_type='transfer'
    debt_direction: str | None = None    # required when operation_type='debt'
    counterparty_id: int | None = None   # merchant/service for regular/refund parts
    debt_partner_id: int | None = None   # debtor/creditor for operation_type='debt'
    amount: Decimal
    description: str | None = None


class ImportRowUpdateRequest(BaseModel):
    account_id: int | None = None
    target_account_id: int | None = None
    credit_account_id: int | None = None
    category_id: int | None = None
    counterparty_id: int | None = None
    debt_partner_id: int | None = None
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
    warning_count: int = 0
    error_count: int
    # Mirrors session.summary_json["auto_preview"]["status"]:
    # pending | running | ready | failed | skipped | null (never attempted).
    auto_preview_status: str | None = None
    # Auto-account-recognition Шаг 4 — extractor-detected bank+type are
    # echoed on every queue entry so the frontend can render the inline
    # «Это <Bank> <Type>?» prompt without an extra getImportSession call.
    # All optional: legacy sessions and unknown-bank uploads leave them null.
    bank_code: str | None = None
    account_type_hint: str | None = None
    contract_number: str | None = None
    statement_account_number: str | None = None
    suggested_bank_id: int | None = None


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
    debt_partner_id: int | None = None
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


# ── Brand confirm/reject (Brand registry Ph6) ──────────────────────────


class BrandConfirmRequest(BaseModel):
    brand_id: int = Field(ge=1)
    # Optional: when set, used as the category for this brand globally for
    # the user. Default behaviour (no field) → resolver looks up by hint.
    category_id: int | None = Field(default=None, ge=1)


class BrandConfirmResponse(BaseModel):
    row_id: int
    brand_id: int
    brand_slug: str
    brand_canonical_name: str
    counterparty_id: int | None = None
    counterparty_name: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    propagated_count: int
    was_override: bool


class BrandRejectResponse(BaseModel):
    row_id: int
    rejected_brand_id: int


class ApplyBrandCategoryRequest(BaseModel):
    """Set per-user category override for a brand and bulk-apply to
    active rows. Standalone endpoint (post-confirmation editing flow)."""
    category_id: int = Field(ge=1)


class ApplyBrandCategoryResponse(BaseModel):
    brand_id: int
    brand_canonical_name: str
    category_id: int
    category_name: str
    rows_updated: int
    override_id: int
