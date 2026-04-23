'use client';

/**
 * Bulk-cluster review card (И-08 Этап 3).
 *
 * Renders one fingerprint or brand cluster with:
 *   - collapsed header: brand/skeleton + count + total amount + suggested
 *     category + "Подтвердить всё" button
 *   - expanded body: virtualized row list with per-row checkbox (include/
 *     exclude from the batch) and inline category override
 *
 * Bulk-action panel on top applies one category + one operation_type across
 * all still-checked rows. Sticky edits (rows the user modified individually)
 * are not overwritten by subsequent bulk-apply clicks.
 *
 * Contract with backend: `POST /imports/{id}/clusters/bulk-apply` expects a
 * flat list of per-row updates, so this component never sends "one category
 * for all" — it expands the UI choice into N explicit row updates before
 * hitting the API.
 */

import { memo, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { bulkApplyCluster } from '@/lib/api/imports';
import { createCounterparty, getCounterparties } from '@/lib/api/counterparties';
import type {
  BulkApplyPayload,
  BulkClusterRowUpdate,
  BulkFingerprintCluster,
  ImportPreviewRow,
} from '@/types/import';
import type { Category } from '@/types/category';
import type { Counterparty } from '@/types/counterparty';

export type ClusterCardMeta =
  | {
      kind: 'fingerprint';
      cluster: BulkFingerprintCluster;
    }
  | {
      kind: 'brand';
      brand: string;
      direction: string;
      count: number;
      totalAmount: string;
      members: BulkFingerprintCluster[];
    };

type Props = {
  meta: ClusterCardMeta;
  sessionId: number;
  rowsById: Map<number, ImportPreviewRow>;
  categories: Category[];
  onApplied: () => void;
};

// Per-row client state — picked category/counterparty and include/exclude.
// Keyed by row.id so toggling "expand brand" doesn't reset selections.
// `edited` flags point out which fields were set manually (so bulk-apply
// doesn't overwrite them).
type RowState = {
  categoryId: number | null;
  counterpartyId: number | null;
  included: boolean;
  categoryEdited: boolean;
  counterpartyEdited: boolean;
};

function formatMoney(value: string | number): string {
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(Math.abs(n));
}

function ClusterCardImpl({ meta, sessionId, rowsById, categories, onApplied }: Props) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [bulkCategoryId, setBulkCategoryId] = useState<number | null>(
    meta.kind === 'fingerprint' ? meta.cluster.candidate_category_id : null,
  );
  const [bulkQuery, setBulkQuery] = useState('');
  const [bulkCounterpartyId, setBulkCounterpartyId] = useState<number | null>(null);
  const [bulkCounterpartyQuery, setBulkCounterpartyQuery] = useState('');
  const [rowState, setRowState] = useState<Record<number, RowState>>({});

  const counterpartiesQuery = useQuery({
    queryKey: ['counterparties'],
    queryFn: getCounterparties,
  });
  const counterparties: Counterparty[] = counterpartiesQuery.data ?? [];
  const counterpartyById = useMemo(() => {
    const map = new Map<number, Counterparty>();
    for (const cp of counterparties) map.set(cp.id, cp);
    return map;
  }, [counterparties]);

  const createCounterpartyMutation = useMutation({
    mutationFn: (name: string) => createCounterparty({ name }),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      setBulkCounterpartyId(created.id);
      setBulkCounterpartyQuery(created.name);
      toast.success(`Контрагент «${created.name}» создан`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать контрагента'),
  });

  // Aggregate rows across members (brand) or use the single cluster's ids.
  const allRowIds = useMemo<number[]>(() => {
    if (meta.kind === 'brand') {
      return meta.members.flatMap((m) => m.row_ids);
    }
    return meta.cluster.row_ids;
  }, [meta]);

  const rows = useMemo<ImportPreviewRow[]>(
    () => allRowIds.map((id) => rowsById.get(id)).filter((r): r is ImportPreviewRow => !!r),
    [allRowIds, rowsById],
  );

  // Only show categories compatible with the cluster direction.
  const filteredCategories = useMemo<Category[]>(() => {
    const direction = meta.kind === 'fingerprint' ? meta.cluster.direction : meta.direction;
    const wanted = direction === 'income' ? 'income' : 'expense';
    return categories.filter((c) => c.kind === wanted);
  }, [categories, meta]);

  const categoryItems = useMemo<SearchSelectItem[]>(
    () => filteredCategories.map((c) => ({ value: String(c.id), label: c.name })),
    [filteredCategories],
  );

  const categoryById = useMemo(() => {
    const map = new Map<number, Category>();
    for (const c of categories) map.set(c.id, c);
    return map;
  }, [categories]);

  // Title + subtitle for the collapsed header.
  // Transfer-like fingerprint clusters carry a concrete identifier (phone /
  // contract / card / iban) — prefer that over the masked skeleton so users
  // see "Перевод по номеру телефона +79…6612" instead of "… <PHONE>".
  const title =
    meta.kind === 'brand'
      ? meta.brand.charAt(0).toUpperCase() + meta.brand.slice(1)
      : meta.cluster.identifier_value
        ? headerFromIdentifier(
            meta.cluster.identifier_key ?? null,
            meta.cluster.identifier_value,
            meta.cluster.skeleton,
          )
        : headerFromSkeleton(meta.cluster.skeleton);
  const count = meta.kind === 'brand' ? meta.count : meta.cluster.count;
  const totalAmount = meta.kind === 'brand' ? meta.totalAmount : String(meta.cluster.total_amount);
  const direction = meta.kind === 'brand' ? meta.direction : meta.cluster.direction;
  const subtitle = `${count} операц${count === 1 ? 'ия' : count < 5 ? 'ии' : 'ий'} · ${formatMoney(totalAmount)}`;

  function defaultRowState(): RowState {
    return {
      categoryId: bulkCategoryId,
      counterpartyId: bulkCounterpartyId,
      included: true,
      categoryEdited: false,
      counterpartyEdited: false,
    };
  }

  function getRowState(rowId: number): RowState {
    return rowState[rowId] ?? defaultRowState();
  }

  function toggleRowIncluded(rowId: number) {
    setRowState((prev) => {
      const current = prev[rowId] ?? defaultRowState();
      return { ...prev, [rowId]: { ...current, included: !current.included } };
    });
  }

  function setRowCategory(rowId: number, categoryId: number | null) {
    setRowState((prev) => {
      const current = prev[rowId] ?? defaultRowState();
      return { ...prev, [rowId]: { ...current, categoryId, categoryEdited: true } };
    });
  }

  function applyBulkToAllIncluded() {
    if (bulkCategoryId == null && bulkCounterpartyId == null) {
      toast.error('Выбери категорию или контрагента для массового применения');
      return;
    }
    setRowState((prev) => {
      const next: Record<number, RowState> = { ...prev };
      for (const row of rows) {
        const current = next[row.id] ?? defaultRowState();
        if (!current.included) continue;
        next[row.id] = {
          ...current,
          // sticky: don't overwrite fields the user already tweaked individually
          categoryId: current.categoryEdited ? current.categoryId : (bulkCategoryId ?? current.categoryId),
          counterpartyId: current.counterpartyEdited ? current.counterpartyId : (bulkCounterpartyId ?? current.counterpartyId),
        };
      }
      return next;
    });
  }

  const applyMutation = useMutation({
    mutationFn: async () => {
      const updates: BulkClusterRowUpdate[] = [];
      for (const row of rows) {
        const s = getRowState(row.id);
        if (!s.included) continue;
        if (s.categoryId == null) continue; // can't confirm a row without category
        updates.push({
          row_id: row.id,
          category_id: s.categoryId,
          counterparty_id: s.counterpartyId,
          operation_type: 'regular',
        });
      }
      if (updates.length === 0) {
        throw new Error('Ни одной строки с выбранной категорией');
      }
      const payload: BulkApplyPayload = {
        cluster_key:
          meta.kind === 'brand' ? meta.brand : meta.cluster.fingerprint,
        cluster_type: meta.kind,
        updates,
      };
      return bulkApplyCluster(sessionId, payload);
    },
    onSuccess: async (data) => {
      const skipped = data.skipped_row_ids.length;
      if (skipped > 0) {
        toast.info(
          `Подтверждено ${data.confirmed_count}, пропущено ${skipped} (уже импортированы)`,
        );
      } else {
        toast.success(`Подтверждено ${data.confirmed_count} строк${data.rules_affected > 0 ? `, обновлено правил: ${data.rules_affected}` : ''}`);
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'preview'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'bulk-clusters'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'moderation-status'] }),
      ]);
      onApplied();
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось применить'),
  });

  const includedCount = rows.reduce((acc, r) => acc + (getRowState(r.id).included ? 1 : 0), 0);
  const withCategoryCount = rows.reduce(
    (acc, r) => acc + (getRowState(r.id).included && getRowState(r.id).categoryId != null ? 1 : 0),
    0,
  );
  const suggestedCategory =
    bulkCategoryId != null ? categoryById.get(bulkCategoryId)?.name : null;

  // Counterparty items for SearchSelect — all user counterparties, with a
  // "+ Создать «…»" option that appears when the query doesn't match anything.
  const counterpartyItems = useMemo<SearchSelectItem[]>(
    () => counterparties.map((cp) => ({ value: String(cp.id), label: cp.name })),
    [counterparties],
  );
  const trimmedCpQuery = bulkCounterpartyQuery.trim();
  const exactCpMatch = counterparties.some(
    (cp) => cp.name.toLowerCase() === trimmedCpQuery.toLowerCase(),
  );
  const canCreateCounterparty = trimmedCpQuery.length > 0 && !exactCpMatch && !createCounterpartyMutation.isPending;

  return (
    <Card className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-soft">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-slate-50"
      >
        <span className="shrink-0 text-slate-400">
          {expanded ? <ChevronDown className="size-5" /> : <ChevronRight className="size-5" />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold text-slate-900">{title}</p>
          <p className="text-sm text-slate-600">{subtitle}</p>
        </div>
        {suggestedCategory ? (
          <span className="shrink-0 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
            {suggestedCategory}
          </span>
        ) : (
          <span className="shrink-0 text-xs text-slate-400">Выбери категорию</span>
        )}
        <span
          className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
            direction === 'income'
              ? 'bg-emerald-50 text-emerald-700'
              : 'bg-slate-100 text-slate-700'
          }`}
        >
          {direction === 'income' ? 'Доход' : 'Расход'}
        </span>
      </button>

      {expanded ? (
        <div>
          <div className="border-t border-slate-100 bg-slate-50 px-4 py-3">
            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
              <div>
                <SearchSelect
                  id={`bulk-cat-${title}`}
                  label="Категория для всех включённых"
                  placeholder="Найти или создать…"
                  widthClassName="w-full"
                  query={bulkQuery}
                  setQuery={setBulkQuery}
                  items={categoryItems}
                  selectedValue={bulkCategoryId != null ? String(bulkCategoryId) : null}
                  onSelect={(item) => {
                    setBulkCategoryId(Number(item.value));
                    setBulkQuery(item.label);
                  }}
                  showAllOnFocus
                />
              </div>
              <div>
                <SearchSelect
                  id={`bulk-cp-${title}`}
                  label="Контрагент (необязательно)"
                  placeholder="Найти или создать…"
                  widthClassName="w-full"
                  query={bulkCounterpartyQuery}
                  setQuery={setBulkCounterpartyQuery}
                  items={counterpartyItems}
                  selectedValue={bulkCounterpartyId != null ? String(bulkCounterpartyId) : null}
                  onSelect={(item) => {
                    setBulkCounterpartyId(Number(item.value));
                    setBulkCounterpartyQuery(item.label);
                  }}
                  showAllOnFocus
                  createAction={{
                    visible: canCreateCounterparty,
                    label: trimmedCpQuery ? `+ Создать «${trimmedCpQuery}»` : '',
                    onClick: () => {
                      if (trimmedCpQuery) createCounterpartyMutation.mutate(trimmedCpQuery);
                    },
                  }}
                />
              </div>
              <div className="flex items-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={applyBulkToAllIncluded}
                  disabled={bulkCategoryId == null && bulkCounterpartyId == null}
                >
                  Применить ко всем
                </Button>
                <Button
                  type="button"
                  onClick={() => applyMutation.mutate()}
                  disabled={applyMutation.isPending || withCategoryCount === 0}
                >
                  {applyMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      Сохраняю…
                    </>
                  ) : (
                    <>Подтвердить {withCategoryCount} / {includedCount}</>
                  )}
                </Button>
              </div>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Исключённые строки вернутся в очередь «Требуют внимания».
              Контрагента можно не привязывать. Точечные правки не перезаписываются кнопкой «Применить ко всем».
            </p>
          </div>

          <ClusterRowList
            rows={rows}
            getRowState={getRowState}
            toggleRowIncluded={toggleRowIncluded}
            setRowCategory={setRowCategory}
            categories={filteredCategories}
          />
        </div>
      ) : null}
    </Card>
  );
}

// Row list — split into its own component so hook order is stable, and the
// virtualizer only mounts when the card is actually expanded. Uses a scrollable
// inner container (max-h) with per-row CSS `content-visibility: auto` fallback
// via virtualization. Per-row category picker is a NATIVE <select> — no portal,
// no listeners, no layout recomputation across rows.
function ClusterRowList({
  rows,
  getRowState,
  toggleRowIncluded,
  setRowCategory,
  categories,
}: {
  rows: ImportPreviewRow[];
  getRowState: (rowId: number) => RowState;
  toggleRowIncluded: (rowId: number) => void;
  setRowCategory: (rowId: number, categoryId: number | null) => void;
  categories: Category[];
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 44,
    overscan: 8,
  });

  const items = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();
  const maxHeight = Math.min(rows.length * 44 + 4, 12 * 44);

  return (
    <div
      ref={scrollRef}
      className="overflow-y-auto"
      style={{ maxHeight }}
    >
      <div style={{ height: totalSize, position: 'relative' }}>
        {items.map((virtualRow) => {
          const row = rows[virtualRow.index];
          const s = getRowState(row.id);
          return (
            <div
              key={row.id}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
              className={`flex items-center gap-3 border-b border-slate-100 px-4 py-2 text-sm ${s.included ? '' : 'opacity-50'}`}
            >
              <input
                type="checkbox"
                checked={s.included}
                onChange={() => toggleRowIncluded(row.id)}
                className="size-4 shrink-0"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-slate-800">{descriptionOf(row)}</p>
                <p className="text-xs text-slate-400">#{row.row_index} · {dateOf(row)} · {amountOf(row)}</p>
              </div>
              <select
                className="w-40 shrink-0 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-slate-50 disabled:text-slate-400"
                value={s.categoryId != null ? String(s.categoryId) : ''}
                disabled={!s.included}
                onChange={(e) => {
                  const val = e.target.value;
                  setRowCategory(row.id, val ? Number(val) : null);
                }}
              >
                <option value="">— категория —</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function headerFromSkeleton(skeleton: string): string {
  // Simple prettify — take the first 80 chars of the skeleton, capitalize.
  const s = (skeleton || '').trim();
  if (!s) return 'Паттерн';
  const trimmed = s.length > 80 ? s.slice(0, 80) + '…' : s;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

// Build a human-readable title from the cluster's concrete identifier. We
// still show the skeleton verb ("Внешний перевод по номеру") so users can
// tell transfer-types apart, then substitute the <PLACEHOLDER> with the
// real value. Falls back to the skeleton if substitution can't place the
// value meaningfully.
function headerFromIdentifier(
  key: string | null,
  value: string,
  skeleton: string,
): string {
  const placeholderByKey: Record<string, string> = {
    phone: '<PHONE>',
    contract: '<CONTRACT>',
    card: '<CARD>',
    iban: '<IBAN>',
    person_hash: '<PERSON>',
  };
  const placeholder = key ? placeholderByKey[key] : undefined;
  const s = (skeleton || '').trim();
  if (placeholder && s.includes(placeholder.toLowerCase())) {
    const replaced = s.replace(placeholder.toLowerCase(), value);
    const trimmed = replaced.length > 80 ? replaced.slice(0, 80) + '…' : replaced;
    return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
  }
  // Fallback: concatenate skeleton + identifier in parens.
  const base = headerFromSkeleton(skeleton);
  return `${base} · ${value}`;
}

function descriptionOf(row: ImportPreviewRow): string {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  return (
    String(nd.description ?? nd.original_description ?? '') ||
    (row.raw_data as Record<string, string> | undefined)?.description ||
    '—'
  );
}

function amountOf(row: ImportPreviewRow): string {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  const amount = Number(nd.amount ?? 0);
  const direction = String(nd.direction ?? 'expense');
  const sign = direction === 'income' ? '+' : '−';
  return `${sign} ${formatMoney(amount)}`;
}

function dateOf(row: ImportPreviewRow): string {
  const nd = (row.normalized_data || {}) as Record<string, any>;
  const raw =
    (nd.date as string | undefined) ??
    (nd.operation_date as string | undefined) ??
    (nd.transaction_date as string | undefined) ??
    (row.raw_data as Record<string, string> | undefined)?.date;
  if (!raw) return '—';
  const parsed = new Date(raw);
  if (!Number.isNaN(parsed.getTime())) {
    return new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
    }).format(parsed);
  }
  return String(raw);
}

export const ClusterCard = memo(ClusterCardImpl);
