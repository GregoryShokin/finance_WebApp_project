import { apiClient } from '@/lib/api/client';
import type { CategoryRule, CategoryRuleFilters } from '@/types/category-rule';

export function getCategoryRules(filters: CategoryRuleFilters = {}) {
  const params = new URLSearchParams();
  if (filters.scope) params.set('scope', filters.scope);
  if (typeof filters.is_active === 'boolean') {
    params.set('is_active', String(filters.is_active));
  }
  const qs = params.toString();
  return apiClient<CategoryRule[]>(`/category-rules${qs ? `?${qs}` : ''}`);
}
