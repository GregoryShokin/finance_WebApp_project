'use client';

/**
 * BrandPickerModal — single entry point for «привязать к бренду» on a row.
 *
 * Layout:
 *   • Top: search input + «+ Создать новый бренд» button.
 *   • Body: list of matching brands (private + global), debounced search.
 *   • Click a brand → confirmRowBrand → close.
 *   • Click «+ Создать новый бренд» → opens BrandCreateModal nested inside
 *     this picker. On successful create, both close.
 *
 * Replaces the earlier two-button design («+ Создать бренд» / «Выбрать
 * бренд») on the row — there is only one entry point now, with create
 * surfaced as a fallback inside the picker.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Search } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { type Brand, listBrands } from '@/lib/api/brands';
import { confirmRowBrand } from '@/lib/api/imports';
import { BrandCreateModal } from './brand-create-modal';
import type { CreatableOption } from '@/components/ui/creatable-select';

export function BrandPickerModal({
  open,
  rowId,
  sessionId,
  rawDescription,
  categoryOptions,
  onClose,
}: {
  open: boolean;
  rowId: number;
  sessionId: number;
  /** Raw description of the source row, shown to BrandCreateModal as context. */
  rawDescription: string;
  /** Expense-kind categories shared with brand-prompt; passed to nested create modal. */
  categoryOptions: (CreatableOption & { kind?: 'income' | 'expense' })[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [createOpen, setCreateOpen] = useState(false);

  // Reset query state on open so the picker doesn't leak from a previous row.
  useEffect(() => {
    if (open) {
      setQ('');
      setDebouncedQ('');
      setCreateOpen(false);
    }
  }, [open]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const brandsQuery = useQuery({
    queryKey: ['brands-list', debouncedQ],
    queryFn: () => listBrands({ q: debouncedQ || undefined, limit: 50 }),
    enabled: open && !createOpen,
    staleTime: 30_000,
  });

  const confirmMut = useMutation({
    mutationFn: (brand: Brand) => confirmRowBrand(rowId, brand.id, null),
    onSuccess: (_resp, brand) => {
      toast.success(`Привязано к «${brand.canonical_name}»`);
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось привязать бренд'),
  });

  const brands = brandsQuery.data ?? [];

  return (
    <>
      <Dialog
        open={open && !createOpen}
        onClose={onClose}
        title="Выбрать бренд"
        description="Поиск по существующим брендам — глобальные и ваши приватные."
      >
        <div className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
              <input
                type="text"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Поиск по названию…"
                autoFocus
                className="w-full rounded-md border border-line bg-bg-surface pl-8 pr-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setCreateOpen(true)}
              title="Создать новый бренд"
              className="gap-1.5"
            >
              <Plus className="size-4" /> Создать
            </Button>
          </div>

          <div className="max-h-72 overflow-y-auto rounded-md border border-line bg-bg-surface">
            {brandsQuery.isLoading ? (
              <div className="px-3 py-4 text-center text-xs text-ink-3">Загрузка…</div>
            ) : brands.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-ink-3">
                {debouncedQ ? (
                  <>
                    <div>Не нашли «{debouncedQ}» среди брендов.</div>
                    <button
                      type="button"
                      onClick={() => setCreateOpen(true)}
                      className="mt-2 inline-flex items-center gap-1 rounded-md border border-line bg-bg-surface2 px-2.5 py-1 text-[12px] text-ink hover:bg-bg-surface"
                    >
                      <Plus className="size-3" /> Создать «{debouncedQ}»
                    </button>
                  </>
                ) : (
                  'Список пуст'
                )}
              </div>
            ) : (
              <ul className="divide-y divide-line">
                {brands.map((b) => (
                  <li key={b.id}>
                    <button
                      type="button"
                      disabled={confirmMut.isPending}
                      onClick={() => confirmMut.mutate(b)}
                      className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-bg-surface2 disabled:opacity-60"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-ink">{b.canonical_name}</div>
                        <div className="truncate text-[11px] text-ink-3">
                          {b.is_global ? 'глобальный' : 'приватный'}
                          {b.category_hint ? ` · ${b.category_hint}` : ''}
                        </div>
                      </div>
                      <span className="text-[11px] text-ink-3">{b.slug}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="flex justify-end">
            <Button type="button" variant="ghost" onClick={onClose}>
              Закрыть
            </Button>
          </div>
        </div>
      </Dialog>

      {createOpen ? (
        <BrandCreateModal
          open={createOpen}
          rowId={rowId}
          sessionId={sessionId}
          rawDescription={rawDescription}
          categoryOptions={categoryOptions}
          onClose={(success) => {
            setCreateOpen(false);
            if (success) onClose();  // also close picker — brand was bound
          }}
        />
      ) : null}
    </>
  );
}
