'use client';

/**
 * BrandPickerModal — «Выбрать другой бренд» from the brand-prompt UI.
 *
 * Scope filter: combined private + global by default. The user types into
 * the search box; we hit `GET /brands?q=…&limit=50` debounced. Selecting
 * a brand calls the same `confirmRowBrand` flow as the inline prompt's
 * [Да], so behaviour stays identical to the auto-resolved case (counterparty
 * + category materialisation, propagation across same-brand siblings).
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { type Brand, listBrands } from '@/lib/api/brands';
import { confirmRowBrand } from '@/lib/api/imports';

export function BrandPickerModal({
  open,
  rowId,
  onClose,
}: {
  open: boolean;
  rowId: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');

  // Reset query state on open so the picker doesn't leak from a previous row.
  useEffect(() => {
    if (open) {
      setQ('');
      setDebouncedQ('');
    }
  }, [open]);

  // Debounce typing — 250 ms is enough to stop key-by-key network spam
  // without feeling laggy.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const brandsQuery = useQuery({
    queryKey: ['brands-list', debouncedQ],
    queryFn: () => listBrands({ q: debouncedQ || undefined, limit: 50 }),
    enabled: open,
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
    <Dialog
      open={open}
      onClose={onClose}
      title="Выбрать бренд"
      description="Поиск по существующим брендам — глобальные и ваши приватные."
    >
      <div className="space-y-3">
        <div className="relative">
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

        <div className="max-h-72 overflow-y-auto rounded-md border border-line bg-bg-surface">
          {brandsQuery.isLoading ? (
            <div className="px-3 py-4 text-center text-xs text-ink-3">Загрузка…</div>
          ) : brands.length === 0 ? (
            <div className="px-3 py-4 text-center text-xs text-ink-3">
              {debouncedQ ? 'Ничего не найдено' : 'Бренды не загружены'}
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
  );
}
