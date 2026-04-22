import { apiClient } from '@/lib/api/client';
import type { Bank } from '@/types/account';

export function getBanks(query?: string) {
  const params = query ? `?q=${encodeURIComponent(query)}` : '';
  return apiClient<Bank[]>(`/banks${params}`);
}
