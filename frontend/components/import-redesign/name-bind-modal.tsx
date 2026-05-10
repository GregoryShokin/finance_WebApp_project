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
import {
  addBrandPattern,
  applyBrandToSession,
  createBrand,
  suggestBrandFromRow,
  type BrandPatternKind,
} from '@/lib/api/brands';
import {
  bindImportRowName,
  confirmRowBrand,
  searchImportNames,
  type BindImportNameResponse,
  type NameSearchItem,
} from '@/lib/api/imports';

const PATTERN_KIND_LABEL: Record<BrandPatternKind, string> = {
  text: 'Подстрока в описании',
  sbp_merchant_id: 'SBP merchant_id',
  org_full: 'Полное название юр. лица',
  alias_exact: 'Точное совпадение',
};

const PATTERN_KIND_OPTIONS: CreatableOption[] = (
  ['text', 'sbp_merchant_id', 'org_full', 'alias_exact'] as BrandPatternKind[]
).map((k) => ({ value: k, label: PATTERN_KIND_LABEL[k] }));

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
  // Editable pattern fields (kind=brand + creating new). Prefilled from
  // /brands/suggest-from-row so the user sees WHICH skeleton token the
  // resolver will use as the recognition signal — and can override it
  // before saving. Empty values mean «let the backend auto-learn». For
  // existing brands and contacts these are unused.
  const [patternKind, setPatternKind] = useState<BrandPatternKind>('text');
  const [patternValue, setPatternValue] = useState('');
  const [patternTouched, setPatternTouched] = useState(false);

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
      setPatternKind('text');
      setPatternValue('');
      setPatternTouched(false);
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

  // Brand-suggest prefill — shows the user the row's extracted candidate
  // token (text-pattern from the skeleton, or sbp_merchant_id when
  // present). Only relevant for kind=brand AND when creating a new brand
  // (no item picked from the search list).
  const suggestQuery = useQuery({
    queryKey: ['brand-suggest-from-row', rowId],
    queryFn: () => suggestBrandFromRow(rowId),
    enabled: open && kind === 'brand' && rowId > 0,
    staleTime: 0,
  });

  // Sync the suggestion into the editable fields on first arrival, but
  // never overwrite a value the user has already typed. The user's edit
  // is sticky — flipping radio off and back, or refetching, doesn't blow
  // away their input.
  useEffect(() => {
    if (!suggestQuery.data || patternTouched) return;
    const s = suggestQuery.data;
    if (s.pattern_kind) setPatternKind(s.pattern_kind);
    if (s.pattern_value) setPatternValue(s.pattern_value);
    // Pre-seed the search input with the suggested canonical name when
    // the user hasn't typed anything yet — saves a step on the common
    // «just confirm what the system found» case.
    if (s.canonical_name && !q.trim()) setQ(s.canonical_name);
  }, [suggestQuery.data, patternTouched, q]);

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

  // Explicit-pattern create flow (kind=brand, no existing_id). Mirrors
  // the pre-v1.27 BrandCreateModal sequence: createBrand → addPattern →
  // confirmRowBrand → applyBrandToSession. We split this off from
  // `bindMut` because `bind-name` always defers pattern selection to the
  // backend's auto-learn — for new brands we want the user's chosen
  // (kind, value) pair to be authoritative instead.
  const createBrandMut = useMutation({
    mutationFn: async (vars: {
      name: string;
      patternKind: BrandPatternKind;
      patternValue: string;
      category_id?: number | null;
    }) => {
      const trimmedName = vars.name.trim();
      const trimmedPattern = vars.patternValue.trim();
      if (!trimmedName) throw new Error('Введите название бренда');
      if (!trimmedPattern) throw new Error('Укажите паттерн распознавания');

      const brand = await createBrand({
        canonical_name: trimmedName,
        category_hint: null,
      });
      await addBrandPattern(brand.id, {
        kind: vars.patternKind,
        pattern: trimmedPattern,
        is_regex: false,
      });
      // skipAutoLearn=true — user just authored the recognition pattern
      // explicitly via «По чему распознавать»; we must not let the
      // confirm path auto-learn a parallel generic token that competes
      // with their choice.
      await confirmRowBrand(rowId, brand.id, vars.category_id ?? null, {
        skipAutoLearn: true,
      });
      let sweptCount = 0;
      try {
        const apply = await applyBrandToSession(brand.id);
        sweptCount = apply.confirmed ?? 0;
      } catch {
        // Sweep is best-effort.
      }
      return { brand, sweptCount };
    },
    onSuccess: ({ brand, sweptCount }) => {
      const extra = sweptCount > 0 ? ` (+${sweptCount} ${pluralRows(sweptCount)})` : '';
      toast.success(`Бренд «${brand.canonical_name}» создан${extra}`);
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
      queryClient.invalidateQueries({ queryKey: ['brand-suggested-groups'] });
      onClose();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось создать бренд'),
  });

  const isPending = bindMut.isPending || createBrandMut.isPending;

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
    // New brand creation goes through the explicit-pattern path so the
    // user's chosen pattern is used as the recognition signal — auto-learn
    // doesn't get a chance to second-guess them.
    if (kind === 'brand') {
      if (!patternValue.trim()) {
        toast.error('Укажи паттерн распознавания');
        return;
      }
      createBrandMut.mutate({
        name,
        patternKind,
        patternValue,
        category_id: categoryId,
      });
      return;
    }
    bindMut.mutate({ kind, name, category_id: categoryId });
  };

  const canSave = (picked != null || q.trim().length > 0) && !isPending;

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

        {/* Pattern editor — visible only when creating a NEW brand
            (kind=brand AND nothing picked from the list). Shows the
            user WHICH skeleton token the resolver will use as the
            recognition signal, and lets them override it. Mirrors the
            pre-v1.27 BrandCreateModal UX. */}
        {kind === 'brand' && picked == null ? (
          <div className="rounded-md border border-line bg-bg-surface2 p-3">
            <div className="mb-1.5 text-[11px] font-medium text-ink-2">
              По чему распознавать
            </div>
            <div className="grid grid-cols-[180px_1fr] gap-2">
              <CreatableSelect
                value={patternKind}
                options={PATTERN_KIND_OPTIONS}
                onChange={(v) => {
                  setPatternKind(v as BrandPatternKind);
                  setPatternTouched(true);
                }}
                width={180}
              />
              <input
                type="text"
                value={patternValue}
                onChange={(e) => {
                  setPatternValue(e.target.value);
                  setPatternTouched(true);
                }}
                placeholder={
                  suggestQuery.isLoading
                    ? 'Подбираем…'
                    : 'Например: vkusnoitochka'
                }
                className="rounded-md border border-line bg-bg-surface px-3 py-1.5 text-sm text-ink focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <div className="mt-1.5 text-[10.5px] text-ink-3">
              {patternKind === 'text'
                ? 'Подстрока в нормализованном описании. Минимум 3 символа.'
                : patternKind === 'sbp_merchant_id'
                ? 'Точный merchant_id СБП — самый сильный сигнал.'
                : patternKind === 'org_full'
                ? 'Полное название юр. лица — для случаев «ООО Ромашка».'
                : 'Точное совпадение всего нормализованного описания.'}
            </div>
          </div>
        ) : null}

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
            {isPending ? 'Сохраняем…' : 'Сохранить'}
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
