import { apiClient } from '@/lib/api/client';
import type { Bank } from '@/types/account';

export function getBanks(query?: string, options?: { supportedOnly?: boolean }) {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (options?.supportedOnly) params.set('supported_only', 'true');
  const qs = params.toString();
  return apiClient<Bank[]>(`/banks${qs ? `?${qs}` : ''}`);
}
