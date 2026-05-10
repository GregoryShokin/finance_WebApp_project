'use client';

/**
 * NameBindModal — single moderator entry point that replaces both the
 * legacy «Выбрать бренд» picker and the inline DebtPartner picker on
 * import rows. The user types one name, optionally pins a category,
 * picks Brand vs Contact (locked to Contact on debt rows per §12.2),
 * and the backend routes to the right entity.
 *
 * Layout:
 *   • Search input (debounced) → unified results list with «бренд» /
 *     «контакт» tags. Picking a result calls bindImportRowName with
 *     `existing_id` set.
 *   • Radio: ○ Бренд  ● Контакт. Default chosen by the row's tokens
 *     (org/sbp_merchant_id → brand; phone/contract/person → contact).
 *     Disabled when `lockedKind` is set (debt rows).
 *   • Optional category select; hint clarifies that for brands the
 *     category pins for ALL operations (override), for contacts it's
 *     only a hint stored on the contact's `default_category_id`.
 *   • «Сохранить» — when nothing is selected from the list, sends `name`
 *     to the backend so it creates the entity. On success we toast and
 *     invalidate preview / bulk-cluster queries.
 */

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { CreatableSelect, type CreatableOption } from '@/components/ui/creatable-select';
import { applyBrandToSession } from '@/lib/api/brands';
import {
  bindImportRowName,
  searchImportNames,
  type BindImportNameResponse,
  type NameSearchItem,
} from '@/lib/api/imports';

type Kind = 'brand' | 'contact';

export function NameBindModal({
  open,
  rowId,
  defaultKind,
  lockedKind,
  rawDescription,
  categoryOptions,
  onClose,
  onSuccess,
}: {
  open: boolean;
  rowId: number;
  defaultKind: Kind;
  /** When set, the radio is disabled and pinned to this kind. Used on
   * debt rows where §12.2 forces Contact. */
  lockedKind?: Kind | null;
  /** Source row description — shown as context above the search box so
   * the user remembers which row they're naming. */
  rawDescription: string;
  categoryOptions: (CreatableOption & { kind?: 'income' | 'expense' })[];
  onClose: () => void;
  onSuccess?: (result: BindImportNameResponse) => void;
}) {
  const queryClient = useQueryClient();
  const [q, setQ] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [kind, setKindRaw] = useState<Kind>(lockedKind || defaultKind);
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [picked, setPicked] = useState<NameSearchItem | null>(null);

  const setKind = (next: Kind) => {
    if (lockedKind) return;
    setKindRaw(next);
    // Switching kind invalidates the picked item — its id is type-specific.
    setPicked(null);
  };

  // Reset state on every fresh open so the modal doesn't leak across rows.
  useEffect(() => {
    if (open) {
      setQ('');
      setDebouncedQ('');
      setKindRaw(lockedKind || defaultKind);
      setCategoryId(null);
      setPicked(null);
    }
  }, [open, defaultKind, lockedKind]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const searchQuery = useQuery({
    queryKey: ['import-names', debouncedQ],
    queryFn: () => searchImportNames(debouncedQ, 20),
    enabled: open,
    staleTime: 30_000,
  });

  const items = searchQuery.data?.items ?? [];
  const filteredItems = useMemo(
    () => items.filter((i) => i.kind === kind),
    [items, kind],
  );

  const bindMut = useMutation({
    mutationFn: async (vars: {
      kind: Kind;
      name?: string;
      existing_id?: number;
      category_id?: number | null;
    }) => {
      const bound = await bindImportRowName(rowId, {
        kind: vars.kind,
        name: vars.name,
        existing_id: vars.existing_id,
        category_id: vars.category_id ?? null,
      });
      // Brand-kind: sweep every other unbound row of the user against the
      // brand's pattern set so siblings catch up in one click. Without this,
      // the resolver's prompt-threshold (0.65) leaves rows whose final score
      // sits a hair below it (e.g. global brand with 1 historical rejection)
      // unstamped — picking the brand on one row would miss the other 12.
      // `apply_brand_to_session` is deliberately permissive (no threshold),
      // matches the pre-v1.27 BrandPickerModal flow.
      let sweptCount = 0;
      if (bound.kind === 'brand') {
        try {
          const apply = await applyBrandToSession(bound.id);
          sweptCount = apply.confirmed ?? 0;
        } catch {
          // Sweep is best-effort. The single-row bind already succeeded;
          // surface the toast for the row and let the user retry the rest.
        }
      }
      return { bound, sweptCount };
    },
    onSuccess: ({ bound, sweptCount }) => {
      const total = (bound.propagated_count || 0) + (sweptCount || 0);
      const extra = total > 0 ? ` (+${total} ${pluralRows(total)})` : '';
      toast.success(`Привязано к «${bound.name}»${extra}`);
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      queryClient.invalidateQueries({ queryKey: ['brand-suggested-groups'] });
      onSuccess?.(bound);
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось привязать имя'),
  });

  const handleSave = () => {
    if (picked) {
      bindMut.mutate({
        kind: picked.kind,
        existing_id: picked.id,
        category_id: categoryId,
      });
      return;
    }
    const name = q.trim();
    if (!name) {
      toast.error('Введи имя или выбери из списка');
      return;
    }
    bindMut.mutate({ kind, name, category_id: categoryId });
  };

  const canSave = (picked != null || q.trim().length > 0) && !bindMut.isPending;

  const categoryHint = kind === 'brand'
    ? 'Категория закрепится за этим брендом для всех операций.'
    : 'Категория — необязательная подсказка, привяжется к контакту.';

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Имя контрагента"
      description={
        rawDescription
          ? `Из выписки: ${rawDescription}`
          : 'Назови контрагента строки — бренд или личный контакт.'
      }
    >
      <div className="space-y-3">
        <div className="flex items-center gap-3 text-[12px] text-ink-2">
          <KindRadio
            value={kind}
            onChange={setKind}
            disabled={!!lockedKind}
          />
          {lockedKind ? (
            <span className="text-[11px] text-ink-3">
              Долговая операция — только контакт.
            </span>
          ) : null}
        </div>

        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
          <input
            type="text"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPicked(null);
            }}
            placeholder="Имя или название…"
            autoFocus
            className="w-full rounded-md border border-line bg-bg-surface pl-8 pr-3 py-2 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>

        <div className="max-h-60 overflow-y-auto rounded-md border border-line bg-bg-surface">
          {searchQuery.isLoading ? (
            <div className="px-3 py-4 text-center text-xs text-ink-3">Поиск…</div>
          ) : filteredItems.length === 0 ? (
            <div className="px-3 py-6 text-center text-xs text-ink-3">
              {debouncedQ
                ? `Создадим новое: «${debouncedQ}» — нажми «Сохранить».`
                : 'Введи имя для поиска или создания нового.'}
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {filteredItems.map((it) => {
                const isPicked = picked?.kind === it.kind && picked?.id === it.id;
                return (
                  <li key={`${it.kind}-${it.id}`}>
                    <button
                      type="button"
                      onClick={() => setPicked(isPicked ? null : it)}
                      className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-bg-surface2 ${
                        isPicked ? 'bg-bg-surface2 ring-1 ring-accent' : ''
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="truncate text-ink">{it.name}</div>
                        <div className="truncate text-[11px] text-ink-3">
                          {it.kind === 'brand'
                            ? (it.is_global ? 'бренд · глобальный' : 'бренд · приватный')
                            : 'контакт'}
                          {it.category_name ? ` · ${it.category_name}` : ''}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div>
          <div className="mb-1 text-[11px] text-ink-3">Категория (необязательно)</div>
          <CreatableSelect
            value={categoryId != null ? String(categoryId) : null}
            options={categoryOptions}
            onChange={(v) => setCategoryId(v ? Number(v) : null)}
            placeholder="— без категории —"
            width={420}
          />
          <div className="mt-1 text-[10.5px] text-ink-3">{categoryHint}</div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button type="button" onClick={handleSave} disabled={!canSave}>
            {bindMut.isPending ? 'Сохраняем…' : 'Сохранить'}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function KindRadio({
  value,
  onChange,
  disabled,
}: {
  value: Kind;
  onChange: (v: Kind) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex items-center gap-3 text-[12px]">
      <KindRadioOption
        label="Бренд"
        active={value === 'brand'}
        disabled={disabled}
        onClick={() => onChange('brand')}
      />
      <KindRadioOption
        label="Контакт"
        active={value === 'contact'}
        disabled={disabled}
        onClick={() => onChange('contact')}
      />
    </div>
  );
}

function KindRadioOption({
  label,
  active,
  disabled,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 transition disabled:cursor-not-allowed disabled:opacity-60 ${
        active
          ? 'border-accent bg-accent/10 text-ink'
          : 'border-line bg-bg-surface text-ink-2 hover:border-line-strong hover:text-ink'
      }`}
    >
      <span
        className={`grid size-3.5 place-items-center rounded-full border ${
          active ? 'border-accent' : 'border-line'
        }`}
      >
        {active ? <span className="size-2 rounded-full bg-accent" /> : null}
      </span>
      {label}
    </button>
  );
}

function pluralRows(n: number): string {
  const last = n % 10;
  const tens = n % 100;
  if (tens >= 11 && tens <= 14) return 'строк';
  if (last === 1) return 'строка';
  if (last >= 2 && last <= 4) return 'строки';
  return 'строк';
}
