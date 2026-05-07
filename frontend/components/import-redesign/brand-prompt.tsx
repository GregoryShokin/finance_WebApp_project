/**
 * BrandPrompt — inline «Это <brand>?» banner with optional category override.
 *
 * Visibility rules (Brand registry §7 UX):
 *   • normalized_data.brand_id is set (resolver matched a brand above threshold)
 *   • normalized_data.user_confirmed_brand_id is null (not yet confirmed)
 *   • normalized_data.user_rejected_brand_id is null (not previously rejected)
 *   • operation_type ∈ {regular, refund} — transfers/debts don't carry a brand
 *
 * Three actions:
 *   • [Да]  — confirmRowBrand(brandId, selectedCategoryId): bumps pattern.confirms,
 *             saves user-brand category override if changed, propagates same-brand
 *             confirmation + counterparty + category to every row of this session.
 *   • [Нет] — rejectRowBrand: bumps pattern.rejections, stamps the row's
 *             rejection so resolver does not re-suggest on next read.
 *   • Category dropdown — defaults to the brand's hint; picking a different one
 *             saves it as a per-user override (applied to all same-brand rows
 *             on confirm).
 */
'use client';

import { useMemo, useState } from 'react';
import { Tag } from 'lucide-react';

import { CategorySelect } from '@/components/import/entity-selects';

export type CategoryOption = {
  value: string;          // category id as string
  label: string;          // category name
  kind?: 'income' | 'expense';
};

export type BrandPromptData = {
  brand_id: number;
  brand_canonical_name: string;
  brand_category_hint?: string | null;
};

function _findHintCategoryId(
  hint: string | null | undefined,
  categories: CategoryOption[],
): number | null {
  if (!hint) return null;
  const target = hint.toLowerCase();
  for (const c of categories) {
    if (c.label.toLowerCase() === target) return Number(c.value);
  }
  return null;
}

export function BrandPrompt({
  data,
  categories,
  isPending,
  onConfirm,
  onReject,
}: {
  data: BrandPromptData;
  // Filter applied client-side: usually expense-kind for typical merchant
  // brands. Caller is responsible for passing the right slice.
  categories: CategoryOption[];
  isPending?: boolean;
  // Ph8: confirm callback now carries the chosen categoryId so the user
  // can override the brand's default hint at the moment of confirmation.
  onConfirm: (brandId: number, categoryId: number | null) => void;
  onReject: () => void;
}) {
  const defaultId = useMemo(
    () => _findHintCategoryId(data.brand_category_hint, categories),
    [data.brand_category_hint, categories],
  );
  const [selectedId, setSelectedId] = useState<number | null>(defaultId);

  return (
    <div className="mt-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-[13px]">
      <div className="flex items-start gap-2">
        <Tag className="mt-0.5 size-4 shrink-0 text-emerald-600" />
        <div className="min-w-0 flex-1">
          <p className="text-emerald-900">
            Это{' '}
            <span className="font-semibold">«{data.brand_canonical_name}»</span>?
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <label className="text-xs text-emerald-900">Категория:</label>
            <CategorySelect
              value={selectedId}
              options={categories}
              onChange={setSelectedId}
              kind="expense"
              width={220}
              disabled={isPending}
            />
            <button
              type="button"
              disabled={isPending}
              onClick={() => onConfirm(data.brand_id, selectedId)}
              className="rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
            >
              ✓ Да
            </button>
            <button
              type="button"
              disabled={isPending}
              onClick={onReject}
              className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            >
              Нет
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
