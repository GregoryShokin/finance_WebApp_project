import { apiClient } from '@/lib/api/client';
import type { FinancialHealth, RealAsset, RealAssetPayload } from '@/types/financial-health';

export function getFinancialHealth() {
  return apiClient<FinancialHealth>('/financial-health');
}

export function getRealAssets() {
  return apiClient<RealAsset[]>('/real-assets');
}

export function createRealAsset(payload: RealAssetPayload) {
  return apiClient<RealAsset>('/real-assets', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateRealAsset(id: number, payload: Partial<RealAssetPayload>) {
  return apiClient<RealAsset>(`/real-assets/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteRealAsset(id: number) {
  return apiClient<void>(`/real-assets/${id}`, { method: 'DELETE' });
}
