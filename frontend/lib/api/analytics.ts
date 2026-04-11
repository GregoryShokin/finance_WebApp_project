import { apiClient } from '@/lib/api/client';
import type { LargePurchasesList } from '@/types/transaction';

export function getLargePurchases(months = 6) {
  return apiClient<LargePurchasesList>(`/analytics/large-purchases?months=${months}`);
}
