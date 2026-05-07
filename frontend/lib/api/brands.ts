/**
 * Brand-management endpoints (Brand registry Ph8b).
 *
 * Read-only endpoints (`GET /brands`, suggestions) feed the picker and the
 * «Создать бренд?» widget; mutating endpoints (`POST /brands`, `POST
 * /brands/{id}/patterns`) only ever author **private** brands and patterns.
 *
 * Note: `applyBrandCategory` and `confirmRowBrand`/`rejectRowBrand` live in
 * `imports.ts` for historical reasons (Ph7/Ph8 landed there first). They
 * stay there to avoid churn; new Ph8b endpoints land here.
 */

import { apiClient } from '@/lib/api/client';

export type BrandPatternKind = 'text' | 'sbp_merchant_id' | 'org_full' | 'alias_exact';

export type Brand = {
  id: number;
  slug: string;
  canonical_name: string;
  category_hint: string | null;
  is_global: boolean;
  created_by_user_id: number | null;
};

export type BrandPattern = {
  id: number;
  kind: BrandPatternKind;
  pattern: string;
  is_regex: boolean;
  is_global: boolean;
  is_active: boolean;
};

export type BrandWithPatterns = Brand & { patterns: BrandPattern[] };

export type BrandSuggestion = {
  canonical_name: string | null;
  pattern_kind: BrandPatternKind | null;
  pattern_value: string | null;
};

export type SuggestedBrandGroup = {
  candidate: string;
  row_count: number;
  sample_descriptions: string[];
  sample_row_ids: number[];
};

export function createBrand(payload: {
  canonical_name: string;
  category_hint?: string | null;
}) {
  return apiClient<Brand>('/brands', {
    method: 'POST',
    body: JSON.stringify({
      canonical_name: payload.canonical_name,
      category_hint: payload.category_hint ?? null,
    }),
  });
}

export function listBrands(params?: {
  q?: string;
  scope?: 'private' | 'global';
  limit?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.q) qs.set('q', params.q);
  if (params?.scope) qs.set('scope', params.scope);
  if (params?.limit) qs.set('limit', String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiClient<Brand[]>(`/brands${suffix}`);
}

export function getBrand(brandId: number) {
  return apiClient<BrandWithPatterns>(`/brands/${brandId}`);
}

export function updateBrand(brandId: number, payload: {
  canonical_name?: string;
  category_hint?: string | null;
}) {
  return apiClient<Brand>(`/brands/${brandId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export type DeleteBrandResponse = {
  brand_id: number;
  rows_cleared: number;
};

export function deleteBrand(brandId: number) {
  return apiClient<DeleteBrandResponse>(`/brands/${brandId}`, {
    method: 'DELETE',
  });
}

export function addBrandPattern(brandId: number, payload: {
  kind: BrandPatternKind;
  pattern: string;
  is_regex?: boolean;
}) {
  return apiClient<BrandPattern>(`/brands/${brandId}/patterns`, {
    method: 'POST',
    body: JSON.stringify({
      kind: payload.kind,
      pattern: payload.pattern,
      is_regex: payload.is_regex ?? false,
    }),
  });
}

export function suggestBrandFromRow(rowId: number) {
  return apiClient<BrandSuggestion>(
    `/brands/suggest-from-row?row_id=${encodeURIComponent(rowId)}`,
  );
}

export type ApplyBrandToSessionResponse = {
  matched: number;
  confirmed: number;
  skipped_user_decision: number;
  skipped_already_resolved: number;
};

export function applyBrandToSession(brandId: number, sessionId: number) {
  return apiClient<ApplyBrandToSessionResponse>(
    `/brands/${brandId}/apply-to-session?session_id=${sessionId}`,
    { method: 'POST', body: JSON.stringify({}) },
  );
}

export function listSuggestedBrandGroups(sessionId?: number) {
  const suffix = sessionId != null ? `?session_id=${sessionId}` : '';
  return apiClient<{ suggestions: SuggestedBrandGroup[] }>(
    `/brands/suggested-groups${suffix}`,
  );
}
