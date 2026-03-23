import { apiClient } from '@/lib/api/client';
import type {
  ImportCommitResponse,
  ImportMappingPayload,
  ImportPreviewResponse,
  ImportPreviewRow,
  ImportReviewQueueResponse,
  ImportUploadResponse,
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

export function commitImport(sessionId: number, importReadyOnly = true) {
  return apiClient<ImportCommitResponse>(`/imports/${sessionId}/commit`, {
    method: 'POST',
    body: JSON.stringify({ import_ready_only: importReadyOnly }),
  });
}


export function getImportReviewQueue() {
  return apiClient<ImportReviewQueueResponse>('/imports/review-queue');
}


export function sendImportRowToReview(rowId: number) {
  return apiClient<ImportPreviewRow>(`/imports/rows/${rowId}/send-to-review`, {
    method: 'POST',
  });
}
