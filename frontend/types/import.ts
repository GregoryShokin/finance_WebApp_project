export type ImportSessionStatus = 'uploaded' | 'analyzed' | 'preview_ready' | 'committed' | 'failed';
export type ImportRowStatus = 'ready' | 'warning' | 'error' | 'duplicate' | 'skipped' | 'committed';
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
  imported_count: number;
  skipped_count: number;
  duplicate_count: number;
  error_count: number;
  review_count: number;
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
