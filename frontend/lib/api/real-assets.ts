import { apiClient } from '@/lib/api/client';
import type { RealAsset } from '@/types/real-asset';

export function getRealAssets() {
  return apiClient<RealAsset[]>('/real-assets');
}

