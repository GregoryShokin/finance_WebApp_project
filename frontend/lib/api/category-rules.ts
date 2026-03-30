import { apiClient } from '@/lib/api/client';
import type { CategoryRule } from '@/types/category-rule';

export function getCategoryRules() {
  return apiClient<CategoryRule[]>('/category-rules');
}
