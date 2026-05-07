/**
 * BrandCategoryEdit — small popover button shown on rows with confirmed brand.
 *
 * Lets the user re-bind a brand's category across every same-brand row of
 * their active sessions in one click. Powered by `applyBrandCategory`
 * (Brand registry Ph8 endpoint), which also persists the choice as a
 * per-user override so future imports inherit it automatically.
 */
'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Pencil } from 'lucide-react';
import { toast } from 'sonner';

import type { CategoryOption } from './brand-prompt';
import { CategorySelect } from '@/components/import/entity-selects';
import { applyBrandCategory } from '@/lib/api/imports';

export function BrandCategoryEdit({
  brandId,
  brandName,
  currentCategoryId,
  categories,
}: {
  brandId: number;
  brandName: string;
  currentCategoryId: number | null;
  categories: CategoryOption[];
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(currentCategoryId);

  const mut = useMutation({
    mutationFn: (categoryId: number) => applyBrandCategory(brandId, categoryId),
    onSuccess: (resp) => {
      toast.success(
        `Категория «${resp.category_name}» применена к «${resp.brand_canonical_name}» (${resp.rows_updated} операций)`,
      );
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      setOpen(false);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось обновить категорию'),
  });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 rounded-md border border-line bg-bg-surface px-2 py-0.5 text-[11px] text-ink-3 hover:bg-bg-surface2 hover:text-ink"
        title={`Изменить категорию для всего бренда «${brandName}»`}
      >
        <Pencil className="size-3" /> Категория для «{brandName}»
      </button>
    );
  }

  return (
    <div className="mt-1 inline-flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-2 py-1 text-[12px]">
      <span className="text-emerald-900">«{brandName}» →</span>
      <CategorySelect
        value={selectedId}
        options={categories}
        onChange={setSelectedId}
        kind="expense"
        width={220}
        disabled={mut.isPending}
      />
      <button
        type="button"
        disabled={mut.isPending || selectedId == null}
        onClick={() => selectedId != null && mut.mutate(selectedId)}
        className="rounded-md bg-emerald-600 px-2 py-0.5 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
      >
        Применить ко всем
      </button>
      <button
        type="button"
        disabled={mut.isPending}
        onClick={() => setOpen(false)}
        className="rounded-md border border-slate-300 bg-white px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-60"
      >
        Отмена
      </button>
    </div>
  );
}
