import { apiClient } from '@/lib/api/client';
import type { Metrics } from '@/types/metrics';

export function getMetrics(month: string) {
  return apiClient<Metrics>(`/metrics?month=${month}`);
}
