
import { apiClient } from '@/lib/api/client';
import type { Category, CategoryKind, CategoryPriority, CategoryRegularity, CreateCategoryPayload, UpdateCategoryPayload } from '@/types/category';

export type CategoriesQuery = {
  kind?: CategoryKind | 'all';
  priority?: CategoryPriority | 'all';
  search?: string;
};

export function getCategories(query?: CategoriesQuery) {
  const params = new URLSearchParams();

  if (query?.kind && query.kind !== 'all') params.set('kind', query.kind);
  if (query?.priority && query.priority !== 'all') params.set('priority', query.priority);
  if (query?.search?.trim()) params.set('search', query.search.trim());

  const qs = params.toString();
  return apiClient<Category[]>(`/categories${qs ? `?${qs}` : ''}`);
}

export function createCategory(payload: CreateCategoryPayload) {
  return apiClient<Category>('/categories', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateCategory(categoryId: number, payload: UpdateCategoryPayload) {
  return apiClient<Category>(`/categories/${categoryId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteCategory(categoryId: number) {
  return apiClient<void>(`/categories/${categoryId}`, {
    method: 'DELETE',
  });
}
