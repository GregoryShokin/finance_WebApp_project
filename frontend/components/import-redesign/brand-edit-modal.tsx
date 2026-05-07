'use client';

/**
 * BrandEditModal — rename / delete a private brand.
 *
 * Loaded lazily via `getBrand` so we can show edit form only for private
 * brands (`is_global=false`). Global brands (seed) are presented as
 * read-only with a clear message — the API would refuse the mutation
 * anyway, but it's nicer to communicate up-front than to fail at submit.
 *
 * Delete is a soft-confirm in the same dialog (toggle reveals «Удалить
 * навсегда» button) — the action clears every reference to this brand
 * across the user's active ImportRows, so we want a deliberate gesture.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { deleteBrand, getBrand, updateBrand } from '@/lib/api/brands';

export function BrandEditModal({
  open,
  brandId,
  onClose,
}: {
  open: boolean;
  brandId: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [hint, setHint] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);

  const brandQuery = useQuery({
    queryKey: ['brand-detail', brandId],
    queryFn: () => getBrand(brandId),
    enabled: open && brandId > 0,
    staleTime: 0,
  });

  useEffect(() => {
    if (!brandQuery.data) return;
    setName(brandQuery.data.canonical_name);
    setHint(brandQuery.data.category_hint ?? '');
    setConfirmDelete(false);
  }, [brandQuery.data]);

  const updateMut = useMutation({
    mutationFn: () =>
      updateBrand(brandId, {
        canonical_name: name.trim(),
        category_hint: hint.trim() || null,
      }),
    onSuccess: (b) => {
      toast.success(`Бренд переименован в «${b.canonical_name}»`);
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      queryClient.invalidateQueries({ queryKey: ['brand-detail', brandId] });
      queryClient.invalidateQueries({ queryKey: ['brands-list'] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось обновить бренд'),
  });

  const deleteMut = useMutation({
    mutationFn: () => deleteBrand(brandId),
    onSuccess: (resp) => {
      toast.success(
        `Бренд удалён${resp.rows_cleared > 0
          ? ` · очищено в ${resp.rows_cleared} ${pluralRows(resp.rows_cleared)}`
          : ''}`,
      );
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      queryClient.invalidateQueries({ queryKey: ['brands-list'] });
      queryClient.invalidateQueries({ queryKey: ['brand-suggested-groups'] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось удалить бренд'),
  });

  const brand = brandQuery.data;
  const isLoading = brandQuery.isLoading;
  const isGlobal = brand?.is_global === true;
  const canSubmit = !!brand && !isGlobal && name.trim().length > 0
    && (name.trim() !== brand.canonical_name || (hint.trim() || null) !== (brand.category_hint ?? null));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Редактировать бренд"
      description={isGlobal
        ? 'Глобальные бренды редактируются мейнтейнером и не доступны для правки.'
        : 'Изменения применятся ко всем строкам этого бренда (display + категория-подсказка).'}
    >
      {isLoading || !brand ? (
        <div className="py-6 text-center text-sm text-ink-3">Загрузка…</div>
      ) : (
        <div className="space-y-4">
          <Field label="Название бренда">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isGlobal || updateMut.isPending || deleteMut.isPending}
              className="w-full rounded-md border border-line bg-bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
            />
          </Field>

          <Field
            label="Категория-подсказка"
            hint="Используется при создании счетов и в picker'е. Можно оставить пустым."
          >
            <input
              type="text"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              disabled={isGlobal || updateMut.isPending || deleteMut.isPending}
              placeholder="Например, Кафе и рестораны"
              className="w-full rounded-md border border-line bg-bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-60"
            />
          </Field>

          {!isGlobal ? (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
              {confirmDelete ? (
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-rose-700">Точно удалить?</span>
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setConfirmDelete(false)}
                    disabled={deleteMut.isPending}
                  >
                    Отмена
                  </Button>
                  <Button
                    type="button"
                    onClick={() => deleteMut.mutate()}
                    disabled={deleteMut.isPending}
                    className="bg-rose-600 text-white hover:bg-rose-700"
                  >
                    {deleteMut.isPending ? 'Удаляю…' : 'Удалить навсегда'}
                  </Button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmDelete(true)}
                  className="inline-flex items-center gap-1 text-[12px] text-rose-600 hover:text-rose-700"
                  disabled={updateMut.isPending}
                >
                  <Trash2 className="size-3.5" /> Удалить бренд
                </button>
              )}
              <div className="ml-auto flex items-center gap-2">
                <Button type="button" variant="ghost" onClick={onClose} disabled={updateMut.isPending}>
                  Отмена
                </Button>
                <Button
                  type="button"
                  disabled={!canSubmit || updateMut.isPending}
                  onClick={() => updateMut.mutate()}
                >
                  {updateMut.isPending ? 'Сохраняю…' : 'Сохранить'}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end">
              <Button type="button" variant="ghost" onClick={onClose}>
                Закрыть
              </Button>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] font-medium uppercase tracking-wide text-ink-3">{label}</span>
      <div className="mt-1">{children}</div>
      {hint ? <span className="mt-1 block text-[11px] text-ink-3">{hint}</span> : null}
    </label>
  );
}

function pluralRows(n: number): string {
  const last = n % 10;
  const tens = n % 100;
  if (tens >= 11 && tens <= 14) return 'строках';
  if (last === 1) return 'строке';
  if (last >= 2 && last <= 4) return 'строках';
  return 'строках';
}
