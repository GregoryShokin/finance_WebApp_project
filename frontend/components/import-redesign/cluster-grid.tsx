'use client';

/**
 * Cluster grid — collapsed cards for "Группы похожих операций".
 * Each card click opens <ClusterModal> with per-row editing.
 *
 * Wires through to the existing /imports/{id}/clusters/bulk-apply endpoint.
 * Per-row sticky edits are still respected: the modal applies a category to
 * all currently *checked* rows; unchecking a row before "Подтвердить" sends
 * it to the singles feed (detachImportRowFromCluster).
 */

import { type ReactNode, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronRight, Loader2, X } from 'lucide-react';
import { toast } from 'sonner';

import { Chip } from '@/components/ui/status-chip';
import { CategorySelect, CounterpartySelect } from '@/components/import/entity-selects';
import { fmtRubSigned } from './format';
import {
  bulkApplyCluster,
  detachImportRowFromCluster,
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

type CardData = {
  key: string;
  type: 'counterparty' | 'brand' | 'fingerprint';
  label: string;          // header text (counterparty name, brand or skeleton)
  count: number;
  totalAmount: string;
  direction: 'income' | 'expense' | string;
  candidateCategoryId: number | null;
  rowIds: number[];
  // Cluster identity for bulk-apply: counterparty cards reference all member
  // fingerprint clusters; standalone fingerprint cards reference one.
  clusterKey: string;
  clusterType: 'fingerprint' | 'brand' | 'counterparty';
};

/**
 * Build the three-layer card list, mirroring the legacy moderation panel:
 *   1. counterparty_groups    — Phase 3 counterparty-centric cards (priority)
 *   2. brand_clusters         — only fingerprints not covered by counterparty
 *   3. fingerprint_clusters   — anything still standalone
 *
 * Each card carries its own rowIds (union of member fingerprint row_ids) so
 * the modal can list and the bulk-apply endpoint can be targeted correctly.
 */
function buildCards(clusters: BulkClustersResponse | null): CardData[] {
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
    const cat = members.find((m) => m.candidate_category_id !== null)?.candidate_category_id ?? null;
    cards.push({
      key: `cp-${g.counterparty_id}-${g.direction}`,
      type: 'counterparty',
      label: g.counterparty_name,
      count: g.count,
      totalAmount: g.total_amount,
      direction: g.direction,
      candidateCategoryId: cat,
      rowIds: members.flatMap((m) => m.row_ids),
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
    const cat = members.find((m) => m.candidate_category_id !== null)?.candidate_category_id ?? null;
    const count = members.reduce((s, m) => s + m.count, 0);
    cards.push({
      key: `brand-${b.brand}-${b.direction}`,
      type: 'brand',
      label: b.brand,
      count,
      totalAmount: b.total_amount,
      direction: b.direction,
      candidateCategoryId: cat,
      rowIds: members.flatMap((m) => m.row_ids),
      clusterKey: b.brand,
      clusterType: 'brand',
    });
  }

  // Layer 3 — standalone fingerprint clusters
  for (const fc of clusters.fingerprint_clusters) {
    if (covered.has(fc.fingerprint)) continue;
    cards.push({
      key: `fp-${fc.fingerprint}`,
      type: 'fingerprint',
      label: fc.skeleton || '(без шаблона)',
      count: fc.count,
      totalAmount: fc.total_amount,
      direction: fc.direction,
      candidateCategoryId: fc.candidate_category_id,
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
  const cards = useMemo(() => buildCards(clusters), [clusters]);
  const [openCard, setOpenCard] = useState<{ card: CardData; origin: { x: number; y: number } } | null>(null);

  const rowsById = useMemo(() => {
    const m = new Map<number, ImportPreviewRow>();
    if (!preview) return m;
    for (const r of preview.rows) m.set(r.id, r);
    return m;
  }, [preview]);

  const categoriesQuery = useQuery({ queryKey: ['categories'], queryFn: () => getCategories() });
  const categories = categoriesQuery.data ?? [];

  const categoryById = useMemo(() => {
    const m = new Map<number, string>();
    for (const c of categories) m.set(c.id, c.name);
    return m;
  }, [categories]);

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
            categoryName={c.candidateCategoryId ? categoryById.get(c.candidateCategoryId) ?? null : null}
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
  onClick,
}: {
  card: CardData;
  categoryName: string | null;
  onClick: (origin: { x: number; y: number }) => void;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        onClick({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
      }}
      className="mb-2 grid w-full grid-cols-[1fr_auto_auto] items-center gap-3.5 rounded-2xl border border-line bg-bg-surface px-4 py-3.5 text-left transition hover:border-ink-3 hover:bg-bg-surface2"
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
      <Chip tone="line">{categoryName ?? 'Категория не выбрана'}</Chip>
      <ChevronRight className="size-3.5 text-ink-3" />
    </button>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Modal — full per-row review of a single cluster.

function ClusterModal({
  sessionId,
  card,
  origin,
  rowsById,
  categoryById,
  onClose,
}: {
  sessionId: number;
  card: CardData;
  origin: { x: number; y: number };
  rowsById: Map<number, ImportPreviewRow>;
  categoryById: Map<number, string>;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();

  const initialChecks = useMemo(() => {
    const m = new Map<number, boolean>();
    for (const id of card.rowIds) m.set(id, true);
    return m;
  }, [card.rowIds]);
  const [checks, setChecks] = useState<Map<number, boolean>>(initialChecks);

  const initialPerRowCat = useMemo(() => {
    const m = new Map<number, number | null>();
    for (const id of card.rowIds) {
      const r = rowsById.get(id);
      const nd = r?.normalized_data as Record<string, unknown> | undefined;
      const cid = (nd?.category_id as number | null) ?? null;
      m.set(id, cid);
    }
    return m;
  }, [card.rowIds, rowsById]);
  const [perRowCat, setPerRowCat] = useState<Map<number, number | null>>(initialPerRowCat);

  const [bulkCategoryId, setBulkCategoryId] = useState<number | null>(card.candidateCategoryId);
  const [bulkCounterpartyId, setBulkCounterpartyId] = useState<number | null>(null);

  const categoriesQuery = useQuery({ queryKey: ['categories'], queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });

  const categoryOptions = useMemo(
    () => (categoriesQuery.data ?? []).map((c) => ({ value: String(c.id), label: c.name })),
    [categoriesQuery.data],
  );
  const counterpartyOptions = useMemo(
    () => (counterpartiesQuery.data ?? []).map((cp) => ({ value: String(cp.id), label: cp.name })),
    [counterpartiesQuery.data],
  );

  const checkedRowIds = useMemo(() => card.rowIds.filter((id) => checks.get(id) !== false), [card.rowIds, checks]);
  const direction: 'income' | 'expense' = card.direction === 'income' ? 'income' : 'expense';

  // Detach unchecked rows individually before bulk-apply.
  const detachMut = useMutation({
    mutationFn: (rowId: number) => detachImportRowFromCluster(rowId),
  });
  const bulkMut = useMutation({
    mutationFn: (payload: BulkApplyPayload) => bulkApplyCluster(sessionId, payload),
  });

  const handleApplyBulk = async () => {
    if (checkedRowIds.length === 0) {
      toast.error('Нет выбранных строк');
      return;
    }
    const updates: BulkClusterRowUpdate[] = checkedRowIds.map((row_id) => {
      const cat = perRowCat.get(row_id) ?? bulkCategoryId;
      return {
        row_id,
        operation_type: 'regular',
        category_id: cat,
        counterparty_id: bulkCounterpartyId,
      };
    });
    try {
      // First detach each unchecked row.
      const unchecked = card.rowIds.filter((id) => checks.get(id) === false);
      for (const id of unchecked) {
        await detachMut.mutateAsync(id);
      }
      const resp = await bulkMut.mutateAsync({
        cluster_key: card.clusterKey,
        cluster_type: card.clusterType,
        updates,
      });
      toast.success(`Подтверждено ${resp.confirmed_count} строк`);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['imports', 'preview', sessionId] }),
        queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters', sessionId] }),
        queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status', sessionId] }),
      ]);
      onClose();
    } catch (e) {
      toast.error((e as Error).message || 'Не удалось применить');
    }
  };

  const inflight = bulkMut.isPending || detachMut.isPending;

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
          className="pointer-events-auto flex max-h-[85vh] w-[min(820px,92vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
        {/* Header */}
        <div className="flex items-center gap-2.5 border-b border-line px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-ink">{card.label}</div>
            <div className="mt-0.5 text-[11.5px] text-ink-3">
              {card.count} операций · {fmtRubSigned(card.totalAmount, card.direction)}
            </div>
          </div>
          {bulkCategoryId ? (
            <Chip tone="violet">
              {categoryById.get(bulkCategoryId) ?? 'Категория'}
            </Chip>
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
                onChange={setBulkCategoryId}
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
                const next = new Map(perRowCat);
                for (const id of checkedRowIds) next.set(id, bulkCategoryId);
                setPerRowCat(next);
                toast.success('Категория применена ко всем включённым строкам');
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-bg-surface px-3 py-2 text-xs font-medium text-ink transition hover:bg-bg-surface2 disabled:opacity-60"
            >
              Применить ко всем
            </button>
            <button
              type="button"
              disabled={inflight || checkedRowIds.length === 0}
              onClick={handleApplyBulk}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3 py-2 text-xs font-medium text-white transition hover:bg-ink-2 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {inflight ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
              Подтвердить {checkedRowIds.length} / {card.rowIds.length}
            </button>
          </div>
          <p className="mt-2 text-[11px] leading-4 text-ink-3">
            Снятая галочка отрезает строку от кластера — она уйдёт в «Требуют твоего внимания»
            для индивидуальной обработки. Контрагента можно не привязывать.
            Точечные правки (per-row категории) не перезаписываются кнопкой «Применить ко всем».
          </p>
        </div>

        {/* Rows */}
        <div className="overflow-auto">
          {card.rowIds.map((id) => {
            const row = rowsById.get(id);
            if (!row) return null;
            const checked = checks.get(id) !== false;
            const perCat = perRowCat.get(id) ?? bulkCategoryId;
            const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
            const date = (nd.date as string) || (row.raw_data?.date as string) || '';
            const desc = (nd.description as string) || (row.raw_data?.description as string) || '';
            const amount = (nd.amount as string | number | null) ?? row.raw_data?.amount ?? null;
            const rowDir = ((nd.direction as 'income' | 'expense') || card.direction) as
              | 'income'
              | 'expense'
              | string;
            return (
              <div
                key={id}
                className="grid grid-cols-[24px_1fr_180px] items-center gap-3 border-b border-line px-5 py-2 text-xs last:border-b-0"
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
                  <div className="truncate text-[12.5px]">{desc || '(без описания)'}</div>
                  <div className="mt-0.5 font-mono text-[10.5px] text-ink-3">
                    #{row.row_index} · {date} · {fmtRubSigned(amount as number | string | null | undefined, rowDir)}
                  </div>
                </div>
                <CategorySelect
                  value={perCat}
                  options={categoryOptions}
                  kind={direction === 'income' ? 'income' : 'expense'}
                  onChange={(catId) => {
                    const next = new Map(perRowCat);
                    next.set(id, catId);
                    setPerRowCat(next);
                  }}
                />
              </div>
            );
          })}
        </div>
        </motion.div>
      </div>
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
