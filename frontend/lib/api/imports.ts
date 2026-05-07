import { apiClient } from '@/lib/api/client';
import type {
  BulkApplyPayload,
  BulkApplyResponse,
  BulkClustersResponse,
  ImportCommitResponse,
  ImportMappingPayload,
  ImportPreviewResponse,
  ImportPreviewRow,
  ImportQueueBulkClustersResponse,
  ImportQueueCommitResponse,
  ImportQueuePreviewResponse,
  ImportQueueStartAllResponse,
  ImportSessionResponse,
  ImportSessionListItem,
  ImportReviewQueueResponse,
  ImportRowUpdatePayload,
  ImportRowUpdateResponse,
  ImportUploadResponse,
  ModerationStatusResponse,
  ParkedQueueResponse,
} from '@/types/import';

export function uploadImportFile(payload: {
  file: File;
  delimiter: string;
  // Этап 0.5: bypass duplicate-file detection. Set after the user picks
  // [Перезаписать] (active duplicate) or [Загрузить как новую] (committed
  // duplicate) in DuplicateStatementModal. Backend creates a new parallel
  // session; the existing one is preserved.
  forceNew?: boolean;
}) {
  const formData = new FormData();
  formData.set('file', payload.file);
  formData.set('delimiter', payload.delimiter);

  // Backend reads `force_new` as a query parameter (FastAPI query param
  // semantics — easier than a multipart string field for a boolean flag).
  const url = payload.forceNew
    ? '/imports/upload?force_new=true'
    : '/imports/upload';

  return apiClient<ImportUploadResponse>(url, {
    method: 'POST',
    body: formData,
  });
}

export function previewImport(sessionId: number, payload: ImportMappingPayload) {
  return apiClient<ImportPreviewResponse>(`/imports/${sessionId}/preview`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getImportPreview(sessionId: number) {
  return apiClient<ImportPreviewResponse>(`/imports/${sessionId}/preview`);
}

export function commitImport(sessionId: number, importReadyOnly = true) {
  return apiClient<ImportCommitResponse>(`/imports/${sessionId}/commit`, {
    method: 'POST',
    body: JSON.stringify({ import_ready_only: importReadyOnly }),
  });
}

export function getImportSessions() {
  return apiClient<{ sessions: ImportSessionListItem[]; total: number }>('/imports/sessions');
}

// ──────────────────────────────────────────────────────────────────
// Unified queue (cross-session moderation, v1.23)
// ──────────────────────────────────────────────────────────────────

export function getImportQueuePreview() {
  return apiClient<ImportQueuePreviewResponse>('/imports/queue/preview');
}

export function getImportQueueBulkClusters() {
  return apiClient<ImportQueueBulkClustersResponse>('/imports/queue/bulk-clusters');
}

export function commitImportQueueConfirmed() {
  return apiClient<ImportQueueCommitResponse>('/imports/queue/commit-confirmed', {
    method: 'POST',
  });
}

export function startImportQueueAll() {
  return apiClient<ImportQueueStartAllResponse>('/imports/queue/start-all', {
    method: 'POST',
  });
}

export function getImportSession(sessionId: number) {
  return apiClient<ImportSessionResponse>(`/imports/${sessionId}`);
}

export function deleteImportSession(sessionId: number) {
  return apiClient<void>(`/imports/${sessionId}`, {
    method: 'DELETE',
  });
}


export function getImportReviewQueue() {
  return apiClient<ImportReviewQueueResponse>('/imports/review-queue');
}


export function assignSessionAccount(sessionId: number, accountId: number) {
  return apiClient<ImportSessionListItem>(`/imports/${sessionId}/account`, {
    method: 'PATCH',
    body: JSON.stringify({ account_id: accountId }),
  });
}

export function updateImportRow(rowId: number, payload: ImportRowUpdatePayload) {
  return apiClient<ImportRowUpdateResponse>(`/imports/rows/${rowId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

// LLM moderation removed from the import pipeline (decision 2026-05-03).
// Stubs return immediately without hitting the backend (which now returns 410).
// Kept so any straggler imports compile while we delete call sites.
export async function getModerationStatus(_sessionId: number): Promise<ModerationStatusResponse> {
  return {
    session_id: _sessionId,
    status: 'disabled',
    total_clusters: 0,
    processed_clusters: 0,
    started_at: null,
    finished_at: null,
    error: null,
  } as unknown as ModerationStatusResponse;
}

export async function startModeration(sessionId: number) {
  return { session_id: sessionId, status: 'disabled' };
}

export function getBulkClusters(sessionId: number) {
  return apiClient<BulkClustersResponse>(`/imports/${sessionId}/clusters`);
}

export function bulkApplyCluster(sessionId: number, payload: BulkApplyPayload) {
  return apiClient<BulkApplyResponse>(`/imports/${sessionId}/clusters/bulk-apply`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export type AttachRowToClusterResponse = {
  row_id: number;
  transaction_id: number | null;
  target_fingerprint: string | null;
  counterparty_id: number | null;
  alias_created: boolean;
  binding_created: boolean;
  source_fingerprint: string | null;
  summary: Record<string, number>;
};

// Legacy: attach to a fingerprint cluster (creates FingerprintAlias).
export function attachRowToCluster(
  sessionId: number,
  rowId: number,
  targetFingerprint: string,
) {
  return apiClient<AttachRowToClusterResponse>(
    `/imports/${sessionId}/rows/${rowId}/attach-to-cluster`,
    {
      method: 'POST',
      body: JSON.stringify({ target_fingerprint: targetFingerprint }),
    },
  );
}

// Preferred Phase 3 path: attach to a counterparty. Creates a
// CounterpartyFingerprint binding so future imports of the same skeleton
// group under the counterparty automatically.
export function attachRowToCounterparty(
  sessionId: number,
  rowId: number,
  counterpartyId: number,
) {
  return apiClient<AttachRowToClusterResponse>(
    `/imports/${sessionId}/rows/${rowId}/attach-to-cluster`,
    {
      method: 'POST',
      body: JSON.stringify({ counterparty_id: counterpartyId }),
    },
  );
}

// Brand confirm/reject (Brand registry Ph6 + Ph8).
export type BrandConfirmResponse = {
  row_id: number;
  brand_id: number;
  brand_slug: string;
  brand_canonical_name: string;
  counterparty_id: number | null;
  counterparty_name: string | null;
  category_id: number | null;
  category_name: string | null;
  propagated_count: number;
  was_override: boolean;
};

export type BrandRejectResponse = {
  row_id: number;
  rejected_brand_id: number;
};

export function confirmRowBrand(
  rowId: number,
  brandId: number,
  categoryId?: number | null,
) {
  // Ph8: optional categoryId overrides the brand's default hint and saves
  // a per-user override so future imports of this brand resolve to the
  // chosen category.
  const body: Record<string, unknown> = { brand_id: brandId };
  if (categoryId != null) body.category_id = categoryId;
  return apiClient<BrandConfirmResponse>(
    `/imports/rows/${rowId}/confirm-brand`,
    { method: 'POST', body: JSON.stringify(body) },
  );
}

export function rejectRowBrand(rowId: number) {
  return apiClient<BrandRejectResponse>(
    `/imports/rows/${rowId}/reject-brand`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

// Ph8: bulk-apply category for an entire brand (post-confirmation editing).
export type ApplyBrandCategoryResponse = {
  brand_id: number;
  brand_canonical_name: string;
  category_id: number;
  category_name: string;
  rows_updated: number;
  override_id: number;
};

export function applyBrandCategory(brandId: number, categoryId: number) {
  return apiClient<ApplyBrandCategoryResponse>(
    `/brands/${brandId}/apply-category`,
    {
      method: 'POST',
      body: JSON.stringify({ category_id: categoryId }),
    },
  );
}

export function parkImportRow(rowId: number) {
  return apiClient<{ session_id: number; row_id: number; status: string; summary: Record<string, number> }>(
    `/imports/rows/${rowId}/park`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function unparkImportRow(rowId: number) {
  return apiClient<{ session_id: number; row_id: number; status: string; summary: Record<string, number> }>(
    `/imports/rows/${rowId}/unpark`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function excludeImportRow(rowId: number) {
  return apiClient<{ session_id: number; row_id: number; status: string; summary: Record<string, number> }>(
    `/imports/rows/${rowId}/exclude`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function unexcludeImportRow(rowId: number) {
  return apiClient<{ session_id: number; row_id: number; status: string; summary: Record<string, number> }>(
    `/imports/rows/${rowId}/unexclude`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function unpairImportRow(rowId: number) {
  return apiClient<{ session_id: number; row_id: number; status: string; summary: Record<string, number> }>(
    `/imports/rows/${rowId}/unpair`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function detachImportRowFromCluster(rowId: number) {
  return apiClient<{ session_id: number; row_id: number; status: string; summary: Record<string, number> }>(
    `/imports/rows/${rowId}/detach-from-cluster`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function getParkedQueue() {
  return apiClient<ParkedQueueResponse>('/imports/parked-queue');
}

export function rematchTransfers() {
  return apiClient<{ status: string }>('/imports/rematch-transfers', { method: 'POST' });
}
