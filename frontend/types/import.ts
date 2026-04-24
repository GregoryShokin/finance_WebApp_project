export type ImportSessionStatus = 'uploaded' | 'analyzed' | 'preview_ready' | 'committed' | 'failed';
export type ImportRowStatus = 'ready' | 'warning' | 'error' | 'duplicate' | 'skipped' | 'committed' | 'parked';

export type ModerationSessionStatus = 'not_started' | 'pending' | 'running' | 'ready' | 'failed' | 'skipped';
export type ClusterModerationStatus = 'ready' | 'skipped';

export type ClusterHypothesis = {
  operation_type: string;
  direction: 'income' | 'expense' | string;
  predicted_category_id: number | null;
  confidence: number;
  reasoning: string;
  follow_up_question: string | null;
};

export type TrustZone = 'green' | 'yellow' | 'red';
export type IdentifierMatch = 'matched' | 'absent' | 'unmatched';

export type ModerationClusterEntry = {
  cluster_fingerprint: string | null;
  status: ClusterModerationStatus | null;
  cluster_row_ids: number[];
  hypothesis: ClusterHypothesis | null;
  // Phase-7 trust signals (nullable — old sessions may not have them).
  trust_zone?: TrustZone | null;
  auto_trust?: boolean | null;
  confidence?: number | null;
  identifier_match?: IdentifierMatch | null;
  identifier_key?: string | null;
  identifier_value?: string | null;
  rule_source?: string | null;
  rule_confirms?: number | null;
  rule_rejections?: number | null;
  candidate_category_id?: number | null;
  count?: number | null;
  total_amount?: string | null;
  skeleton?: string | null;
  bank_code?: string | null;
  // Layer 1: account-context hints
  account_context_operation_type?: string | null;
  account_context_category_id?: number | null;
  account_context_label?: string | null;
  // Layer 2: bank-mechanics hints
  bank_mechanics_operation_type?: string | null;
  bank_mechanics_category_id?: number | null;
  bank_mechanics_label?: string | null;
  bank_mechanics_cross_session_warning?: string | null;
  // Layer 3: global cross-user pattern
  global_pattern_category_id?: number | null;
  global_pattern_category_name?: string | null;
  global_pattern_user_count?: number | null;
  global_pattern_total_confirms?: number | null;
};

export type ModerationStatusResponse = {
  session_id: number;
  status: ModerationSessionStatus;
  total_clusters: number;
  processed_clusters: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  clusters: ModerationClusterEntry[];
  auto_trust_rows?: number;
  attention_rows?: number;
};

export type ParkedQueueItem = {
  session_id: number;
  session_status: string;
  filename: string;
  source_type: string;
  row_id: number;
  row_index: number;
  status: ImportRowStatus;
  raw_data: Record<string, string>;
  normalized_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ParkedQueueResponse = {
  items: ParkedQueueItem[];
  total: number;
};
export type ImportSourceType = 'csv' | 'xlsx' | 'pdf';

export type ImportTableInfo = {
  name: string;
  columns: string[];
  rows: number;
  confidence: number;
};

export type ImportDetection = {
  selected_table: string | null;
  available_tables: ImportTableInfo[];
  field_mapping: Record<string, string | null | undefined>;
  field_confidence: Record<string, number>;
  field_reasons: Record<string, string>;
  column_analysis: Array<{
    name: string;
    coverage: number;
    sample_values: string[];
    scores: Record<string, number>;
    reasons: Record<string, string>;
  }>;
  suggested_date_formats: string[];
  overall_confidence: number;
  confidence_label: 'low' | 'medium' | 'high' | string;
  unresolved_fields: string[];
};

export type ImportUploadResponse = {
  session_id: number;
  filename: string;
  source_type: ImportSourceType;
  status: ImportSessionStatus;
  detected_columns: string[];
  sample_rows: Array<Record<string, string>>;
  total_rows: number;
  extraction: Record<string, unknown>;
  detection: ImportDetection;
  suggested_account_id: number | null;
  contract_number: string | null;
  contract_match_reason: string | null;
  contract_match_confidence: number | null;
  statement_account_number: string | null;
  statement_account_match_reason: string | null;
  statement_account_match_confidence: number | null;
};

export type ImportSessionResponse = {
  id: number;
  user_id: number;
  filename: string;
  source_type: ImportSourceType;
  status: ImportSessionStatus;
  detected_columns: string[];
  parse_settings: Record<string, unknown>;
  mapping_json: Record<string, unknown>;
  summary_json: Record<string, unknown>;
  account_id: number | null;
  currency: string | null;
  created_at: string;
  updated_at: string;
};

export type ImportMappingPayload = {
  account_id: number;
  currency: string;
  date_format: string;
  table_name?: string | null;
  field_mapping: Record<string, string | null>;
  skip_duplicates: boolean;
};

export type ImportPreviewRow = {
  id: number;
  row_index: number;
  status: ImportRowStatus;
  confidence: number;
  confidence_label: 'low' | 'medium' | 'high' | string;
  issues: string[];
  unresolved_fields: string[];
  error_message: string | null;
  review_required: boolean;
  raw_data: Record<string, string>;
  normalized_data: Record<string, unknown>;
};

export type ImportPreviewResponse = {
  session_id: number;
  status: ImportSessionStatus;
  detection: ImportDetection;
  summary: {
    total_rows: number;
    ready_rows: number;
    warning_rows: number;
    error_rows: number;
    duplicate_rows: number;
    skipped_rows: number;
  };
  rows: ImportPreviewRow[];
};

export type ImportCommitResponse = {
  session_id: number;
  status: ImportSessionStatus;
  summary: ImportPreviewResponse['summary'];
  remaining_rows: ImportPreviewRow[];
  imported_count: number;
  skipped_count: number;
  duplicate_count: number;
  error_count: number;
  review_count: number;
};

export type ImportSessionListItem = {
  id: number;
  filename: string;
  source_type: string;
  status: string;
  account_id: number | null;
  created_at: string;
  updated_at: string;
  row_count: number;
  ready_count: number;
  error_count: number;
  auto_preview_status: 'pending' | 'running' | 'ready' | 'failed' | 'skipped' | null;
  transfer_match_status: 'pending' | 'running' | 'ready' | 'failed' | null;
};


export type ImportSplitItem = {
  category_id: number;
  amount: number;
  description?: string | null;
};

export type ImportRowUpdatePayload = {
  account_id?: number | null;
  target_account_id?: number | null;
  credit_account_id?: number | null;
  category_id?: number | null;
  counterparty_id?: number | null;
  amount?: number | null;
  type?: string | null;
  operation_type?: string | null;
  debt_direction?: string | null;
  description?: string | null;
  transaction_date?: string | null;
  currency?: string | null;
  credit_principal_amount?: number | null;
  credit_interest_amount?: number | null;
  split_items?: ImportSplitItem[] | null;
  action?: 'confirm' | 'exclude' | 'restore' | null;
};

export type ImportRowUpdateResponse = {
  session_id: number;
  row: ImportPreviewRow;
  summary: ImportPreviewResponse['summary'];
};


export type ImportReviewRow = {
  id: number;
  session_id: number;
  filename: string;
  row_index: number;
  status: ImportRowStatus;
  review_required: boolean;
  issues: string[];
  raw_data: Record<string, string>;
  normalized_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ImportReviewQueueResponse = {
  total: number;
  rows: ImportReviewRow[];
};


// ─── Bulk clusters (И-08 Этап 2) ─────────────────────────────────────────

export type BulkFingerprintCluster = {
  fingerprint: string;
  count: number;
  total_amount: string;
  direction: string;
  skeleton: string;
  row_ids: number[];
  candidate_category_id: number | null;
  candidate_rule_id: number | null;
  rule_source: string;
  confidence: number;
  trust_zone: TrustZone;
  auto_trust: boolean;
  // Identifier-based header (phone / contract / card / iban / person_hash) for
  // transfer-like clusters — the UI prefers this over the masked skeleton so
  // "Перевод на +79…6612" shows instead of "Перевод на <PHONE>".
  identifier_key?: string | null;
  identifier_value?: string | null;
};

export type BulkBrandCluster = {
  brand: string;
  direction: string;
  count: number;
  total_amount: string;
  fingerprint_cluster_ids: string[];
};

// Phase 3 — counterparty-centric grouping. A counterparty can own many
// fingerprint clusters (different skeletons for the same merchant). The UI
// renders one card per counterparty, collapsing all its members.
export type BulkCounterpartyGroup = {
  counterparty_id: number;
  counterparty_name: string;
  direction: string;
  count: number;
  total_amount: string;
  fingerprint_cluster_ids: string[];
};

export type BulkClustersResponse = {
  session_id: number;
  fingerprint_clusters: BulkFingerprintCluster[];
  brand_clusters: BulkBrandCluster[];
  counterparty_groups?: BulkCounterpartyGroup[];
};

export type BulkClusterRowUpdate = {
  row_id: number;
  operation_type?: string | null;
  category_id?: number | null;
  counterparty_id?: number | null;
  target_account_id?: number | null;
  credit_account_id?: number | null;
  credit_principal_amount?: string | null;
  credit_interest_amount?: string | null;
  debt_direction?: string | null;
};

export type BulkApplyPayload = {
  cluster_key: string;
  cluster_type: 'fingerprint' | 'brand' | 'counterparty';
  updates: BulkClusterRowUpdate[];
};

export type BulkApplyResponse = {
  session_id: number;
  confirmed_count: number;
  skipped_row_ids: number[];
  rules_affected: number;
  summary: {
    total_rows: number;
    ready_rows: number;
    warning_rows: number;
    error_rows: number;
    duplicate_rows: number;
    skipped_rows: number;
  };
};
