import { apiClient } from '@/lib/api/client';
import type {
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

export function getParkedQueue() {
  return apiClient<ParkedQueueResponse>('/imports/parked-queue');
}
