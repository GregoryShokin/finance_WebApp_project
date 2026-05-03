import { apiClient } from '@/lib/api/client';
import type {
  BulkApplyPayload,
  BulkApplyResponse,
  BulkClustersResponse,
  ImportCommitResponse,
  ImportMappingPayload,
  ImportPreviewResponse,
  ImportPreviewRow,
  ImportSessionResponse,
  ImportSessionListItem,
  ImportReviewQueueResponse,
  ImportRowUpdatePayload,
  ImportRowUpdateResponse,
  ImportUploadResponse,
  ModerationStatusResponse,
  ParkedQueueResponse,
} from '@/types/import';

export function uploadImportFile(payload: { file: File; delimiter: string }) {
  const formData = new FormData();
  formData.set('file', payload.file);
  formData.set('delimiter', payload.delimiter);

  return apiClient<ImportUploadResponse>('/imports/upload', {
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

export function getModerationStatus(sessionId: number) {
  return apiClient<ModerationStatusResponse>(`/imports/${sessionId}/moderation-status`);
}

export function startModeration(sessionId: number) {
  return apiClient<{ session_id: number; status: string }>(`/imports/${sessionId}/moderate`, {
    method: 'POST',
    body: JSON.stringify({}),
  });
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
