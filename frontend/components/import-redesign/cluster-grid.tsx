'use client';

/**
 * Cluster grid — collapsed cards for "Группы похожих операций".
 * Each card click opens <ClusterModal> with per-row editing.
 *
 * Wires through to /imports/{id}/clusters/bulk-apply, plus per-row endpoints
 * (exclude, park, detach-from-cluster, update with split_items).
 *
 * Spec §3.2 v1.5 / v1.7: bulk-card badges (category + counterparty) read row
 * consensus from `normalized_data` when cluster.candidate_* is null. Without
 * this fallback, after bulk-apply the badge falls back to "Категория не
 * выбрана" because cluster recompute drops the candidate when fresh-rule
 * confidence is low.
 */

import { type ReactNode, useCallback, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Check,
  ChevronRight,
  Clock,
  Loader2,
  Pencil,
  Split,
  Trash2,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import { Chip } from '@/components/ui/status-chip';
import { CategorySelect, CounterpartySelect } from '@/components/import/entity-selects';
import { fmtDateTime, fmtRubSigned } from './format';
import { SplitModal } from './split-modal';
import { SplitChip } from './split-chip';
import { EditTxRazvorot } from './edit-tx-razvorot';
import {
  attachRowToCounterparty,
  bulkApplyCluster,
  detachImportRowFromCluster,
  excludeImportRow,
  parkImportRow,
} from '@/lib/api/imports';
import { getCategories } from '@/lib/api/categories';
import { getCounterparties } from '@/lib/api/counterparties';
import type {
  BulkApplyPayload,
  BulkClusterRowUpdate,
  BulkClustersResponse,
  ImportPreviewResponse,
  ImportPreviewRow,
} from '@/types/import';
import type { Counterparty } from '@/types/counterparty';

type CardData = {
  key: string;
  type: 'counterparty' | 'brand' | 'fingerprint';
  label: string;
  count: number;
  totalAmount: string;
  direction: 'income' | 'expense' | string;
  candidateCategoryId: number | null;
  /** All distinct category IDs found across member rows (non-null). Used when
   *  candidateCategoryId is null because rows have mixed categories — the card
   *  then shows "Зарплата · +2" instead of "Категория не выбрана". */
  uniqueCategoryIds: number[];
  /** Dominant non-regular/non-refund operation type when ALL rows share one
   *  (e.g. 'debt', 'transfer'). These rows have no category by design, so the
   *  card should show the type label instead of "Выбери категорию". */
  dominantOpType: string | null;
  candidateCounterpartyId: number | null;
  rowIds: number[];
  clusterKey: string;
  clusterType: 'fingerprint' | 'brand' | 'counterparty';
};

// Collect all distinct non-null category IDs across member rows.
function uniqueCategoriesFrom(
  rowIds: number[],
  rowsById: Map<number, ImportPreviewRow>,
): number[] {
  const seen = new Set<number>();
  for (const id of rowIds) {
    const v = (rowsById.get(id)?.normalized_data as Record<string, unknown> | undefined)?.category_id;
    if (v != null) {
      const n = Number(v);
      if (Number.isFinite(n)) seen.add(n);
    }
  }
  return [...seen];
}

// If ALL member rows share the same non-regular/non-refund operation_type,
// return it (e.g. 'debt', 'transfer'). These rows carry no category by design.
function dominantNonCategoryOpType(
  rowIds: number[],
  rowsById: Map<number, ImportPreviewRow>,
): string | null {
  let found: string | null = null;
  for (const id of rowIds) {
    const op = String(
      ((rowsById.get(id)?.normalized_data ?? {}) as Record<string, unknown>).operation_type ?? 'regular',
    ).toLowerCase();
    if (op === 'regular' || op === 'refund') return null; // has category rows — not a pure typed cluster
    if (found === null) found = op;
    else if (found !== op) return null; // mixed op types
  }
  return found;
}

// Per-row consensus across a card's member rows. Returns the unique non-null
// value if all populated rows agree, otherwise null. Used when cluster-level
// `candidate_*` recomputed null after bulk-apply (rule confidence below
// threshold) but every row still carries the user-confirmed value in
// `normalized_data`.
function consensusFrom(
  rowIds: number[],
  rowsById: Map<number, ImportPreviewRow>,
  field: 'category_id' | 'counterparty_id',
): number | null {
  let agreed: number | null = null;
  for (const id of rowIds) {
    const r = rowsById.get(id);
    if (!r) continue;
    const v = (r.normalized_data as Record<string, unknown> | undefined)?.[field];
    if (v == null) continue;
    const n = Number(v);
    if (!Number.isFinite(n)) continue;
    if (agreed == null) agreed = n;
    else if (agreed !== n) return null;
  }
  return agreed;
}

function buildCards(
  clusters: BulkClustersResponse | null,
  rowsById: Map<number, ImportPreviewRow>,
): CardData[] {
  if (!clusters) return [];

  const fpById = new Map<string, BulkClustersResponse['fingerprint_clusters'][number]>();
  for (const fc of clusters.fingerprint_clusters) fpById.set(fc.fingerprint, fc);

  const covered = new Set<string>();
  const cards: CardData[] = [];

  // Layer 1 — counterparty groups
  for (const g of clusters.counterparty_groups ?? []) {
    const members = g.fingerprint_cluster_ids
      .map((id) => fpById.get(id))
      .filter((m): m is NonNullable<typeof m> => !!m);
    if (members.length === 0) continue;
    for (const m of members) covered.add(m.fingerprint);
    const rowIds = members.flatMap((m) => m.row_ids);
    const cat =
      members.find((m) => m.candidate_category_id !== null)?.candidate_category_id ??
      consensusFrom(rowIds, rowsById, 'category_id');
    cards.push({
      key: `cp-${g.counterparty_id}-${g.direction}`,
      type: 'counterparty',
      label: g.counterparty_name,
      count: g.count,
      totalAmount: g.total_amount,
      direction: g.direction,
      candidateCategoryId: cat,
      uniqueCategoryIds: uniqueCategoriesFrom(rowIds, rowsById),
      dominantOpType: dominantNonCategoryOpType(rowIds, rowsById),
      candidateCounterpartyId: g.counterparty_id,
      rowIds,
      clusterKey: g.counterparty_name,
      clusterType: 'counterparty',
    });
  }

  // Layer 2 — brand clusters whose members aren't already in a counterparty card
  for (const b of clusters.brand_clusters) {
    const members = b.fingerprint_cluster_ids
      .map((id) => fpById.get(id))
      .filter((m): m is NonNullable<typeof m> => !!m)
      .filter((m) => !covered.has(m.fingerprint));
    if (members.length === 0) continue;
    for (const m of members) covered.add(m.fingerprint);
    const rowIds = members.flatMap((m) => m.row_ids);
    const cat =
      members.find((m) => m.candidate_category_id !== null)?.candidate_category_id ??
      consensusFrom(rowIds, rowsById, 'category_id');
    const cp = consensusFrom(rowIds, rowsById, 'counterparty_id');
    const count = members.reduce((s, m) => s + m.count, 0);
    cards.push({
      key: `brand-${b.brand}-${b.direction}`,
      type: 'brand',
      label: b.brand,
      count,
      totalAmount: b.total_amount,
      direction: b.direction,
      candidateCategoryId: cat,
      uniqueCategoryIds: uniqueCategoriesFrom(rowIds, rowsById),
      dominantOpType: dominantNonCategoryOpType(rowIds, rowsById),
      candidateCounterpartyId: cp,
      rowIds,
      clusterKey: b.brand,
      clusterType: 'brand',
    });
  }

  // Layer 3 — standalone fingerprint clusters
  for (const fc of clusters.fingerprint_clusters) {
    if (covered.has(fc.fingerprint)) continue;
    const cat =
      fc.candidate_category_id ?? consensusFrom(fc.row_ids, rowsById, 'category_id');
    const cp = consensusFrom(fc.row_ids, rowsById, 'counterparty_id');
    const rawSkeleton = fc.skeleton || '(без шаблона)';
    const label =
      fc.identifier_key && fc.identifier_value
        ? rawSkeleton.replace(`<${fc.identifier_key.toUpperCase()}>`, fc.identifier_value)
        : rawSkeleton;
    cards.push({
      key: `fp-${fc.fingerprint}`,
      type: 'fingerprint',
      label,
      count: fc.count,
      totalAmount: fc.total_amount,
      direction: fc.direction,
      candidateCategoryId: cat,
      uniqueCategoryIds: uniqueCategoriesFrom(fc.row_ids, rowsById),
      dominantOpType: dominantNonCategoryOpType(fc.row_ids, rowsById),
      candidateCounterpartyId: cp,
      rowIds: fc.row_ids,
      clusterKey: fc.fingerprint,
      clusterType: 'fingerprint',
    });
  }

  return cards;
}

export function ClusterGrid({
  sessionId,
  preview,
  clusters,
}: {
  sessionId: number;
  preview: ImportPreviewResponse | null;
  clusters: BulkClustersResponse | null;
}) {
  const rowsById = useMemo(() => {
    const m = new Map<number, ImportPreviewRow>();
    if (!preview) return m;
    for (const r of preview.rows) m.set(r.id, r);
    return m;
  }, [preview]);

  const cards = useMemo(() => buildCards(clusters, rowsById), [clusters, rowsById]);
  const [openCard, setOpenCard] = useState<{ card: CardData; origin: { x: number; y: number } } | null>(null);

  const categoriesQuery = useQuery({ queryKey: ['categories'], queryFn: () => getCategories() });
  const categories = categoriesQuery.data ?? [];

  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const counterparties: Counterparty[] = counterpartiesQuery.data ?? [];

  const categoryById = useMemo(() => {
    const m = new Map<number, string>();
    for (const c of categories) m.set(c.id, c.name);
    return m;
  }, [categories]);

  const counterpartyById = useMemo(() => {
    const m = new Map<number, string>();
    for (const cp of counterparties) m.set(cp.id, cp.name);
    return m;
  }, [counterparties]);

  if (cards.length === 0) {
    return null;
  }

  return (
    <section className="surface-card overflow-hidden">
      <header className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Группы похожих операций <span className="text-ink-3 font-normal">· {cards.length}</span>
          </h3>
          <p className="mt-0.5 text-xs text-ink-3">
            Подтверждай категорию для целой группы — самый быстрый способ.
          </p>
        </div>
      </header>

      <div className="px-3 pb-3">
        {cards.map((c) => (
          <ClusterCardCollapsed
            key={c.key}
            card={c}
            categoryName={c.candidateCategoryId != null ? categoryById.get(c.candidateCategoryId) ?? null : null}
            categoryNames={c.uniqueCategoryIds.map((id) => categoryById.get(id) ?? null).filter((n): n is string => n !== null)}
            counterpartyName={
              // Counterparty-typed cards already use their own name as the
              // header label, so showing a duplicate chip is noise.
              c.type === 'counterparty'
                ? null
                : c.candidateCounterpartyId != null
                  ? counterpartyById.get(c.candidateCounterpartyId) ?? null
                  : null
            }
            onClick={(origin) => setOpenCard({ card: c, origin })}
          />
        ))}
      </div>

      <AnimatePresence>
        {openCard ? (
          <ClusterModal
            sessionId={sessionId}
            card={openCard.card}
            origin={openCard.origin}
            rowsById={rowsById}
            categoryById={categoryById}
            counterpartyById={counterpartyById}
            onClose={() => setOpenCard(null)}
          />
        ) : null}
      </AnimatePresence>
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────────

function ClusterCardCollapsed({
  card,
  categoryName,
  categoryNames,
  counterpartyName,
  onClick,
}: {
  card: CardData;
  categoryName: string | null;
  /** Names of all distinct categories when rows have mixed categories. */
  categoryNames: string[];
  counterpartyName: string | null;
  onClick: (origin: { x: number; y: number }) => void;
}) {
  // single consensus → violet; mixed → first + "+N" in neutral;
  // no categories but typed op (debt/transfer/…) → op label; empty → prompt
  const displayName = categoryName ?? (categoryNames.length === 1 ? categoryNames[0] : null);
  const isMulti = !categoryName && categoryNames.length > 1;
  const opLabel: string | null = (!displayName && !isMulti && card.dominantOpType)
    ? ({ debt: 'Долг', transfer: 'Перевод', investment_buy: 'Инвестиция',
         investment_sell: 'Инвестиция', credit_disbursement: 'Получение кредита',
         credit_early_repayment: 'Досрочное погашение' } as Record<string, string>)[card.dominantOpType] ?? null
    : null;

  return (
    <button
      type="button"
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onClick({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
      }}
      className="mb-2 grid w-full grid-cols-[1fr_auto_auto_auto] items-center gap-3.5 rounded-2xl border border-line bg-bg-surface px-4 py-3.5 text-left transition hover:border-ink-3 hover:bg-bg-surface2"
    >
      <div className="flex min-w-0 items-center gap-3">
        <span
          className={[
            'grid size-[30px] shrink-0 place-items-center rounded-lg text-sm font-semibold',
            card.type === 'counterparty'
              ? 'bg-accent-amber-soft text-accent-amber'
              : card.type === 'brand'
                ? 'bg-accent-blue-soft text-accent-blue'
                : 'bg-accent-violet-soft text-accent-violet',
          ].join(' ')}
        >
          {card.label.charAt(0).toUpperCase() || '·'}
        </span>
        <div className="min-w-0">
          <div className="truncate text-[13.5px] font-semibold text-ink">
            {card.label}
            {card.type === 'brand' ? (
              <span className="ml-2 align-middle text-[10px] font-medium uppercase tracking-wide text-ink-3">бренд</span>
            ) : card.type === 'fingerprint' ? (
              <span className="ml-2 align-middle text-[10px] font-medium uppercase tracking-wide text-ink-3">шаблон</span>
            ) : null}
          </div>
          <div className="mt-0.5 text-[11.5px] text-ink-3">
            {card.count} операций · {fmtRubSigned(card.totalAmount, card.direction)}
          </div>
        </div>
      </div>
      {counterpartyName ? (
        <Chip tone="amber">{counterpartyName}</Chip>
      ) : (
        <span aria-hidden className="hidden" />
      )}
      {isMulti ? (
        <span className="flex items-center gap-1">
          <Chip tone="line">{categoryNames[0]}</Chip>
          <Chip tone="line">+{categoryNames.length - 1}</Chip>
        </span>
      ) : opLabel ? (
        <Chip tone="blue">{opLabel}</Chip>
      ) : (
        <Chip tone={displayName ? 'violet' : 'line'}>
          {displayName ?? 'Выбери категорию'}
        </Chip>
      )}
      <ChevronRight className="size-3.5 text-ink-3" />
    </button>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Per-row type → badge labels. Operations whose type isn't `regular` or
// `refund` no longer show a CategorySelect (no category applies); instead
// they render a read-only chip pair (type + direction) with an edit hint.
type RowTypeBadge = {
  type: string;        // human label of the operation type
  direction?: string;  // optional direction label (lent / payment / buy / etc)
  tone: 'violet' | 'blue' | 'amber' | 'green' | 'red' | 'line';
};

function rowTypeBadge(nd: Record<string, unknown>): RowTypeBadge | null {
  const op = String(nd.operation_type ?? 'regular').toLowerCase();
  if (op === 'regular' || op === 'refund' || !op) return null;

  // Backend folds operation_type='credit_payment' into 'transfer' +
  // requires_credit_split=true (see import_row_editor.py:248). Detect this
  // marker first so the badge renders as «Кредитная операция · Регулярный
  // платёж» rather than as plain «Перевод».
  if (op === 'transfer' && Boolean(nd.requires_credit_split)) {
    return { type: 'Кредитная операция', direction: 'Регулярный платёж', tone: 'red' };
  }
  if (op === 'transfer') {
    return { type: 'Перевод', tone: 'blue' };
  }
  if (op === 'debt') {
    const dir = String(nd.debt_direction ?? '').toLowerCase();
    const dirLabel =
      dir === 'lent' ? 'Я дал в долг' :
      dir === 'borrowed' ? 'Я взял в долг' :
      dir === 'repaid' ? 'Я вернул долг' :
      dir === 'collected' ? 'Мне вернули долг' : undefined;
    return { type: 'Долг', direction: dirLabel, tone: 'amber' };
  }
  if (op === 'investment_buy') {
    return { type: 'Инвестиция', direction: 'Покупка', tone: 'green' };
  }
  if (op === 'investment_sell') {
    return { type: 'Инвестиция', direction: 'Продажа', tone: 'green' };
  }
  if (op === 'credit_disbursement') {
    return { type: 'Кредитная операция', direction: 'Получение', tone: 'red' };
  }
  if (op === 'credit_payment') {
    return { type: 'Кредитная операция', direction: 'Регулярный платёж', tone: 'red' };
  }
  if (op === 'credit_early_repayment') {
    return { type: 'Кредитная операция', direction: 'Досрочное погашение', tone: 'red' };
  }
  return null;
}

// ──────────────────────────────────────────────────────────────────────────
// Modal — full per-row review of a single cluster.

function ClusterModal({
  sessionId,
  card,
  origin,
  rowsById,
  categoryById,
  counterpartyById,
  onClose,
}: {
  sessionId: number;
  card: CardData;
  origin: { x: number; y: number };
  rowsById: Map<number, ImportPreviewRow>;
  categoryById: Map<number, string>;
  counterpartyById: Map<number, string>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  // Local removal set: rows the user excluded / parked / split / detached
  // from this modal session. They disappear from the list optimistically;
  // bulk-apply ignores them. Auto-close when empty.
  const [removed, setRemoved] = useState<Set<number>>(new Set());
  const visibleRowIds = useMemo(
    () => card.rowIds.filter((id) => !removed.has(id)),
    [card.rowIds, removed],
  );

  // Per-row inclusion toggle — unchecked rows are detached from the cluster
  // on bulk-apply (they leave the bulk batch and resurface in the attention
  // feed for individual handling).
  const initialChecks = useMemo(() => {
    const m = new Map<number, boolean>();
    for (const id of card.rowIds) m.set(id, true);
    return m;
  }, [card.rowIds]);
  const [checks, setChecks] = useState<Map<number, boolean>>(initialChecks);

  // Per-row category — initialized from row.normalized_data.category_id so
  // re-opening after bulk-apply restores user choice (spec §3.2 v1.5).
  const initialPerRowCat = useMemo(() => {
    const m = new Map<number, number | null>();
    for (const id of card.rowIds) {
      const r = rowsById.get(id);
      const nd = r?.normalized_data as Record<string, unknown> | undefined;
      m.set(id, nd?.category_id != null ? Number(nd.category_id) : null);
    }
    return m;
  }, [card.rowIds, rowsById]);
  const [perRowCat, setPerRowCat] = useState<Map<number, number | null>>(initialPerRowCat);

  // Initial bulk values pull from card.candidate* — which already includes
  // row-consensus fallback from buildCards. Without this, re-opening a card
  // after bulk-apply showed empty bulk pickers even when every member row
  // carried the user-chosen value.
  const [bulkCategoryId, setBulkCategoryId] = useState<number | null>(card.candidateCategoryId);
  // Track whether the user explicitly chose a category in THIS modal session.
  // Auto-filled candidateCategoryId should NOT be applied on «Подтвердить» —
  // only a user-chosen category (or one set via «Применить ко всем») should.
  const [userPickedBulkCategory, setUserPickedBulkCategory] = useState(false);
  const [bulkCounterpartyId, setBulkCounterpartyId] = useState<number | null>(
    card.candidateCounterpartyId,
  );

  const categoriesQuery = useQuery({ queryKey: ['categories'], queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });

  // `kind` is required so EditTxRazvorot can filter by income/expense via
  // categoryOptionsForKind. Without it the per-type filter empties the list.
  const categoryOptions = useMemo(
    () =>
      (categoriesQuery.data ?? []).map((c) => ({
        value: String(c.id),
        label: c.name,
        kind: c.kind,
        hint: c.kind === 'income' ? 'доход' : undefined,
      })),
    [categoriesQuery.data],
  );
  const counterpartyOptions = useMemo(
    () => (counterpartiesQuery.data ?? []).map((cp) => ({ value: String(cp.id), label: cp.name })),
    [counterpartiesQuery.data],
  );

  const direction: 'income' | 'expense' = card.direction === 'income' ? 'income' : 'expense';

  // Non-regular/refund rows are already saved with their own operation_type;
  // including them in bulk-apply would overwrite the type back to 'regular'.
  // Filter them out of the bulk batch entirely (they still appear in the row
  // list, but with a read-only type badge).
  const isBulkEligible = useCallback(
    (id: number): boolean => {
      const row = rowsById.get(id);
      if (!row) return false;
      const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
      // Individually confirmed rows (stamped by EditTxRazvorot or TxRow confirm)
      // are already saved with the correct operation_type — exclude from bulk-apply
      // so a subsequent «Подтвердить» click cannot overwrite them with 'regular'.
      if (nd.user_confirmed_at) return false;
      // Already-split rows are confirmed — bulk-apply must not overwrite them.
      const splitItems = nd.split_items as unknown[] | null | undefined;
      if (Array.isArray(splitItems) && splitItems.length >= 2) return false;
      const op = String(nd.operation_type ?? 'regular').toLowerCase();
      return op === 'regular' || op === 'refund' || !op;
    },
    [rowsById],
  );
  const checkedRowIds = useMemo(
    () =>
      visibleRowIds.filter(
        (id) => checks.get(id) !== false && isBulkEligible(id),
      ),
    [visibleRowIds, checks, isBulkEligible],
  );

  // ── Mutations ─────────────────────────────────────────────────────────

  const detachMut = useMutation({
    mutationFn: (rowId: number) => detachImportRowFromCluster(rowId),
  });
  const bulkMut = useMutation({
    mutationFn: (payload: BulkApplyPayload) => bulkApplyCluster(sessionId, payload),
  });
  const excludeMut = useMutation({
    mutationFn: (rowId: number) => excludeImportRow(rowId),
  });
  const parkMut = useMutation({
    mutationFn: (rowId: number) => parkImportRow(rowId),
  });

  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['imports', 'preview', sessionId] }),
      queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters', sessionId] }),
      queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status', sessionId] }),
    ]);
  }, [queryClient, sessionId]);

  // Optimistically remove a row from the modal. If it was the last visible
  // row, close. Caller is responsible for the actual API call. Functional
  // setState reads the freshest `removed` to avoid races between concurrent
  // per-row actions.
  const closeOnEmpty = useCallback(
    (rowId: number) => {
      setRemoved((prev) => {
        if (prev.has(rowId)) return prev;
        const next = new Set(prev);
        next.add(rowId);
        const stillVisible = card.rowIds.some((id) => !next.has(id));
        if (!stillVisible) {
          // Defer to next tick so AnimatePresence can run exit animation.
          setTimeout(onClose, 0);
        }
        return next;
      });
    },
    [card.rowIds, onClose],
  );

  const handleExclude = async (rowId: number) => {
    try {
      await excludeMut.mutateAsync(rowId);
      toast.success('Строка исключена');
      closeOnEmpty(rowId);
      invalidate();
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось исключить строку');
    }
  };

  const handlePark = async (rowId: number) => {
    try {
      await parkMut.mutateAsync(rowId);
      toast.success('Строка отложена');
      closeOnEmpty(rowId);
      invalidate();
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось отложить строку');
    }
  };

  // Per-row deep editor — opens EditTxRazvorot for full type/category/etc
  // editing. On success the row may leave the cluster (e.g. switched to
  // transfer / debt / credit) so we optimistically remove it from this modal.
  const [editingFor, setEditingFor] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(null);

  // Split — open SplitModal in portal. On success, the row is committed
  // through updateImportRow (action='confirm') and we hide it from this
  // modal.
  const [splitFor, setSplitFor] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(null);

  // ── Bulk-apply ────────────────────────────────────────────────────────

  // Non-regular/refund rows are saved individually via the pencil editor and
  // already carry status='ready' + user_confirmed_at. They count as "done"
  // toward the modal's progress counter even though bulk-apply skips them.
  const preConfirmedCount = useMemo(
    () => visibleRowIds.filter((id) => !isBulkEligible(id)).length,
    [visibleRowIds, isBulkEligible],
  );
  const totalProgress = checkedRowIds.length + preConfirmedCount;

  const handleApplyBulk = async () => {
    // Force a fresh fetch so we always see the latest row states — including
    // user_confirmed_at and operation_type saved moments ago via EditTxRazvorot.
    // Without this, reading from React state (rowsById) or the cache may still
    // show stale data if the component hasn't re-rendered after the last edit.
    await queryClient.refetchQueries({
      queryKey: ['imports', 'preview', sessionId],
      type: 'active',
    });
    const freshPreview = queryClient.getQueryData<ImportPreviewResponse>(
      ['imports', 'preview', sessionId],
    );
    const freshRowsById = new Map<number, ImportPreviewRow>();
    if (freshPreview) {
      for (const r of freshPreview.rows) freshRowsById.set(r.id, r);
    }
    const isFreshEligible = (id: number): boolean => {
      const row = freshRowsById.get(id) ?? rowsById.get(id);
      if (!row) return false;
      const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
      if (nd.user_confirmed_at) return false;
      const splitItems = nd.split_items as unknown[] | null | undefined;
      if (Array.isArray(splitItems) && splitItems.length >= 2) return false;
      const op = String(nd.operation_type ?? 'regular').toLowerCase();
      return op === 'regular' || op === 'refund' || !op;
    };
    const freshCheckedIds = visibleRowIds.filter(
      (id) => checks.get(id) !== false && isFreshEligible(id),
    );
    const freshPreConfirmed = visibleRowIds.filter((id) => !isFreshEligible(id)).length;

    // Two cases: (a) some regular rows are checked → run bulk-apply for them;
    // (b) only non-regular rows visible → they're already saved, just close.
    if (freshCheckedIds.length === 0) {
      if (freshPreConfirmed > 0) {
        // Non-eligible rows (debt, transfer, etc.) are already individually
        // confirmed. If the user picked a cluster-level counterparty, create
        // the CounterpartyFingerprint binding so these rows are grouped under
        // the counterparty card in ClusterGrid (§6.3 — binding-level grouping
        // is separate from row-level counterparty_id, which stays null for
        // debt rows per §12.2 invariant).
        if (bulkCounterpartyId) {
          const nonEligibleIds = visibleRowIds.filter((id) => !isFreshEligible(id));
          await Promise.allSettled(
            nonEligibleIds.map((rowId) =>
              attachRowToCounterparty(sessionId, rowId, bulkCounterpartyId),
            ),
          );
        }
        invalidate();
        onClose();
        return;
      }
      toast.error('Нет выбранных строк');
      return;
    }
    // Use bulkCategoryId as fallback ONLY when the user explicitly chose it
    // in this modal session. Auto-filled candidateCategoryId must not be forced
    // onto rows when the user clicks «Подтвердить» without touching the header.
    const effectiveBulkCat = userPickedBulkCategory ? bulkCategoryId : null;
    const missingCat = freshCheckedIds.filter((row_id) => {
      const rowFresh = freshRowsById.get(row_id) ?? rowsById.get(row_id);
      const ndCat = ((rowFresh?.normalized_data ?? {}) as Record<string, unknown>).category_id as number | null | undefined;
      return (perRowCat.get(row_id) ?? effectiveBulkCat ?? ndCat) == null;
    });
    if (missingCat.length > 0) {
      toast.error(
        missingCat.length === freshCheckedIds.length
          ? 'Выбери категорию'
          : `У ${missingCat.length} строк нет категории`,
      );
      return;
    }
    const updates: BulkClusterRowUpdate[] = freshCheckedIds.map((row_id) => {
      const rowFresh = freshRowsById.get(row_id) ?? rowsById.get(row_id);
      const rowNd = (rowFresh?.normalized_data ?? {}) as Record<string, unknown>;
      const ndCat = rowNd.category_id as number | null | undefined;
      // Preserve 'refund' operation_type for income rows that were already
      // classified as refunds — bulk-apply must not overwrite them with 'regular'.
      const existingOp = String(rowNd.operation_type ?? 'regular').toLowerCase();
      return {
        row_id,
        operation_type: existingOp === 'refund' ? 'refund' : 'regular',
        category_id: perRowCat.get(row_id) ?? effectiveBulkCat ?? ndCat ?? null,
        counterparty_id: bulkCounterpartyId,
      };
    });
    try {
      const unchecked = visibleRowIds.filter(
        (id) => checks.get(id) === false && isFreshEligible(id),
      );
      // If ≥ 3 rows are unchecked, keep them in their fingerprint clusters
      // so they appear as a separate cluster card for independent review.
      // If < 3, detach them individually into the attention feed.
      if (unchecked.length < 3) {
        for (const id of unchecked) {
          await detachMut.mutateAsync(id);
        }
      }
      const resp = await bulkMut.mutateAsync({
        cluster_key: card.clusterKey,
        cluster_type: card.clusterType,
        updates,
      });
      toast.success(`Подтверждено ${resp.confirmed_count} строк`);
      invalidate();
      onClose();
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось применить');
    }
  };

  const inflight =
    bulkMut.isPending ||
    detachMut.isPending ||
    excludeMut.isPending ||
    parkMut.isPending;

  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[9000] bg-ink/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div className="pointer-events-none fixed inset-0 z-[9001] flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.05 }}
          animate={{ opacity: 1, scale: 1, transition: { duration: 0.32, ease: [0.16, 0.84, 0.3, 1] } }}
          exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.14 } }}
          style={{
            transformOrigin: `${origin.x - window.innerWidth / 2}px ${origin.y - window.innerHeight / 2}px`,
          }}
          className="pointer-events-auto flex max-h-[85vh] w-[min(960px,94vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center gap-2.5 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold text-ink">{card.label}</div>
              <div className="mt-0.5 text-[11.5px] text-ink-3">
                {visibleRowIds.length} операций · {fmtRubSigned(card.totalAmount, card.direction)}
              </div>
            </div>
            {bulkCategoryId ? (
              <Chip tone="violet">{categoryById.get(bulkCategoryId) ?? 'Категория'}</Chip>
            ) : null}
            <Chip tone="line">{direction === 'income' ? 'Доход' : 'Расход'}</Chip>
            <button
              type="button"
              onClick={onClose}
              className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
            >
              <X className="size-3.5" />
            </button>
          </div>

          {/* Bulk-apply controls */}
          <div className="border-b border-line bg-bg-surface px-5 py-4">
            <div className="grid items-end gap-3 lg:grid-cols-[1fr_1fr_auto_auto]">
              <ControlField label="Категория для всех включённых">
                <CategorySelect
                  value={bulkCategoryId}
                  kind={direction === 'income' ? 'income' : 'expense'}
                  options={categoryOptions}
                  onChange={(id) => { setBulkCategoryId(id); setUserPickedBulkCategory(true); }}
                />
              </ControlField>
              <ControlField label="Контрагент (необязательно)">
                <CounterpartySelect
                  value={bulkCounterpartyId}
                  options={counterpartyOptions}
                  onChange={setBulkCounterpartyId}
                />
              </ControlField>
              <button
                type="button"
                disabled={inflight}
                onClick={() => {
                  if (bulkCategoryId == null) {
                    toast.error('Выбери категорию');
                    return;
                  }
                  const nextCat = new Map(perRowCat);
                  for (const id of checkedRowIds) {
                    nextCat.set(id, bulkCategoryId);
                  }
                  setPerRowCat(nextCat);
                  setUserPickedBulkCategory(true);
                  toast.success('Категория применена ко включённым строкам');
                }}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-bg-surface px-3 py-2 text-xs font-medium text-ink transition hover:bg-bg-surface2 disabled:opacity-60"
              >
                Применить ко всем
              </button>
              <button
                type="button"
                disabled={inflight || totalProgress === 0}
                onClick={handleApplyBulk}
                title={
                  preConfirmedCount > 0 && checkedRowIds.length === 0
                    ? `${preConfirmedCount} строк уже сохранены через ✎ — клик закроет окно`
                    : preConfirmedCount > 0
                      ? `${checkedRowIds.length} к подтверждению + ${preConfirmedCount} уже сохранены`
                      : undefined
                }
                className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-2 text-xs font-medium text-white transition hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {inflight ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
                {preConfirmedCount > 0 && checkedRowIds.length === 0
                  ? `Готово ${preConfirmedCount} / ${visibleRowIds.length}`
                  : `Подтвердить ${totalProgress} / ${visibleRowIds.length}`}
              </button>
            </div>
            <p className="mt-2 text-[11px] leading-4 text-ink-3">
              Снятая галочка: при 1–2 строках — выводит их из кластера в «Требуют внимания»;
              при 3+ строках — они образуют отдельный кластер для самостоятельного разбора.
              Точечные правки категории не перезаписываются кнопкой «Применить ко всем».
              Карандаш — детальная правка типа операции. Действия справа: разделить · отложить · исключить.
            </p>
          </div>

          {/* Rows */}
          <div className="overflow-auto">
            {/* Loading guard: preview data hasn't arrived yet — rowsById is
                empty while the React Query fetch is in flight. Show a spinner
                instead of the misleading "Готово N/N" state that appears when
                isBulkEligible returns false for every row (row not found). */}
            {visibleRowIds.length > 0 && visibleRowIds.every((id) => !rowsById.has(id)) ? (
              <div className="flex items-center justify-center gap-2 px-5 py-10 text-xs text-ink-3">
                <Loader2 className="size-3.5 animate-spin" />
                Загружаем строки…
              </div>
            ) : visibleRowIds.length === 0 ? (
              <div className="px-5 py-10 text-center text-xs text-ink-3">
                Все строки обработаны.
              </div>
            ) : null}
            {visibleRowIds.map((id) => {
              const row = rowsById.get(id);
              if (!row) return null;
              const checked = checks.get(id) !== false;
              const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
              // Fallback chain: user's per-row pick → bulk header → already-saved
              // nd.category_id (set e.g. via pencil editor before bulk-apply).
              const ndCatId = nd.category_id as number | null | undefined;
              const perCat = perRowCat.get(id) ?? bulkCategoryId ?? ndCatId ?? null;
              const date = (nd.date as string) || (row.raw_data?.date as string) || '';
              const desc = (nd.description as string) || (row.raw_data?.description as string) || '';
              const amount = (nd.amount as string | number | null) ?? row.raw_data?.amount ?? null;
              const rowDir = ((nd.direction as 'income' | 'expense') || card.direction) as
                | 'income'
                | 'expense'
                | string;
              const rowOp = String(nd.operation_type ?? 'regular').toLowerCase();
              const isRefund = rowOp === 'refund';
              const splitItems = nd.split_items as import('@/types/import').ImportSplitItem[] | null | undefined;
              const isSplit = Array.isArray(splitItems) && splitItems.length >= 2;
              const typeBadge = rowTypeBadge(nd);
              // Checkbox remains operable for all rows — bulk-apply silently
              // filters out non-regular/refund rows via isBulkEligible so
              // their saved operation_type is never overwritten back to
              // 'regular'. Decoupling visual state from bulk-eligibility lets
              // the user freely toggle checkboxes without feeling locked.
              return (
                <div
                  key={id}
                  className="grid grid-cols-[20px_1fr_minmax(180px,auto)_auto] items-center gap-3 border-b border-line px-5 py-2.5 text-xs last:border-b-0"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = new Map(checks);
                      next.set(id, !checked);
                      setChecks(next);
                    }}
                    className="size-3.5 cursor-pointer rounded border-line text-ink focus:ring-ink"
                  />
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-[12.5px]">{desc || '(без описания)'}</span>
                      {isRefund ? (
                        <Chip tone="amber">Возврат</Chip>
                      ) : null}
                    </div>
                    <div className="mt-0.5 font-mono text-[10.5px] text-ink-3">
                      {fmtDateTime(date)} · {fmtRubSigned(amount as number | string | null | undefined, rowDir)}
                    </div>
                  </div>
                  {isSplit ? (
                    <SplitChip
                      parts={splitItems!}
                      categoriesById={categoryById}
                      counterpartiesById={counterpartyById}
                    />
                  ) : typeBadge ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Chip tone={typeBadge.tone}>{typeBadge.type}</Chip>
                      {typeBadge.direction ? (
                        <Chip tone="line">{typeBadge.direction}</Chip>
                      ) : null}
                      <span className="text-[10.5px] text-ink-3">· правка через ✎</span>
                    </div>
                  ) : (
                    <CategorySelect
                      value={perCat}
                      options={categoryOptions}
                      kind={isRefund ? 'expense' : direction === 'income' ? 'income' : 'expense'}
                      onChange={(catId) => {
                        const next = new Map(perRowCat);
                        next.set(id, catId);
                        setPerRowCat(next);
                      }}
                      placeholder="— категория —"
                    />
                  )}
                  <RowActions
                    disabled={inflight}
                    onEdit={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      setEditingFor({
                        row,
                        origin: { x: r.left + r.width / 2, y: r.top + r.height / 2 },
                      });
                    }}
                    onSplit={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      setSplitFor({
                        row,
                        origin: { x: r.left + r.width / 2, y: r.top + r.height / 2 },
                      });
                    }}
                    onPark={() => handlePark(id)}
                    onExclude={() => handleExclude(id)}
                  />
                </div>
              );
            })}
          </div>
        </motion.div>
      </div>

      {splitFor
        ? createPortal(
            <SplitModal
              row={splitFor.row}
              origin={splitFor.origin}
              options={{ categories: categoryOptions }}
              // After split the row stays in the cluster with a split badge.
              // Do NOT call closeOnEmpty — the row should remain visible so
              // the user can see the result and confirm or adjust.
              onSuccess={() => { setSplitFor(null); invalidate(); }}
              onClose={() => setSplitFor(null)}
            />,
            document.body,
          )
        : null}

      {editingFor ? (
        <EditTxRazvorot
          sessionId={sessionId}
          row={editingFor.row}
          origin={editingFor.origin}
          options={{ categories: categoryOptions }}
          // Variant A: rows stay in the cluster after deep edit. The
          // invalidation triggered inside EditTxRazvorot refetches preview
          // data; on next render rows with non-regular operation_type get a
          // read-only type+direction badge instead of CategorySelect, and
          // are excluded from bulk-apply by isBulkEligible.
          onClose={() => setEditingFor(null)}
        />
      ) : null}
    </>
  );
}

function ControlField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] text-ink-3">{label}</div>
      {children}
    </div>
  );
}

function RowActions({
  disabled,
  onEdit,
  onSplit,
  onPark,
  onExclude,
}: {
  disabled: boolean;
  onEdit: (e: React.MouseEvent<HTMLButtonElement>) => void;
  onSplit: (e: React.MouseEvent<HTMLButtonElement>) => void;
  onPark: () => void;
  onExclude: () => void;
}) {
  const btnBase = 'grid size-7 place-items-center rounded-md border transition disabled:opacity-50 disabled:cursor-not-allowed';
  const btnNeutral = `${btnBase} border-line bg-bg-surface text-ink-3 hover:border-ink-3 hover:bg-bg-surface2 hover:text-ink`;
  const btnAmber  = `${btnBase} border-accent-amber/40 bg-accent-amber-soft text-accent-amber hover:bg-accent-amber/20`;
  const btnRed    = `${btnBase} border-accent-red/40 bg-accent-red-soft text-accent-red hover:bg-accent-red/20`;

  return (
    <div className="flex shrink-0 items-center gap-1">
      <button
        type="button"
        title="Подробное редактирование"
        aria-label="Редактировать"
        disabled={disabled}
        onClick={onEdit}
        className={btnNeutral}
      >
        <Pencil className="size-3.5" />
      </button>
      <button
        type="button"
        title="Разделить операцию"
        aria-label="Разделить"
        disabled={disabled}
        onClick={onSplit}
        className={btnNeutral}
      >
        <Split className="size-3.5" />
      </button>
      <button
        type="button"
        title="Отложить — разберусь позже"
        aria-label="Отложить"
        disabled={disabled}
        onClick={onPark}
        className={btnAmber}
      >
        <Clock className="size-3.5" />
      </button>
      <button
        type="button"
        title="Исключить из импорта"
        aria-label="Исключить"
        disabled={disabled}
        onClick={onExclude}
        className={btnRed}
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}
