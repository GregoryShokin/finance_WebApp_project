'use client';

/**
 * "Требуют твоего внимания" — chronological feed of singles (rows that the
 * moderator did NOT auto-trust). Each row is a <TxRow> with type-specific
 * inline editors and traffic-light actions on the right.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Filter } from 'lucide-react';

import { TxRow } from './tx-row';
import { EditTxRazvorot } from './edit-tx-razvorot';
import { SplitModal } from './split-modal';
import { getCategories } from '@/lib/api/categories';
import { getCounterparties } from '@/lib/api/counterparties';
import { getDebtPartners } from '@/lib/api/debt-partners';
import { getAccounts } from '@/lib/api/accounts';
import type {
  BulkClustersResponse,
  ImportPreviewResponse,
  ImportPreviewRow,
} from '@/types/import';

export function AttentionFeed({
  sessionId,
  preview,
  clusters,
}: {
  sessionId: number;
  preview: ImportPreviewResponse | null;
  clusters: BulkClustersResponse | null;
}) {
  // Rows that are part of any bulk-cluster card (counterparty / brand /
  // standalone fingerprint) are handled by ClusterGrid; everything else goes
  // into the singles feed. Every fingerprint cluster surfaces in at least one
  // layer of <ClusterGrid>, so unioning all fingerprint_clusters.row_ids is
  // both necessary and sufficient.
  const inClusterRowIds = useMemo(() => {
    const ids = new Set<number>();
    if (!clusters) return ids;
    for (const fc of clusters.fingerprint_clusters) {
      for (const r of fc.row_ids) ids.add(r);
    }
    return ids;
  }, [clusters]);

  const singles = useMemo<ImportPreviewRow[]>(() => {
    if (!preview) return [];
    return preview.rows.filter((r) => {
      if (r.status === 'committed' || r.status === 'duplicate') return false;
      // Parked / excluded rows live in their own FAB buckets.
      if (r.status === 'parked' || r.status === 'skipped') return false;
      if (inClusterRowIds.has(r.id)) return false;
      // Both matched pairs (transfer_match_meta) and recognition-only
      // transfers (operation_type='transfer') belong to «Переводы и дубли».
      const nd = r.normalized_data as Record<string, unknown> | undefined;
      if (nd?.transfer_match_meta) return false;
      if (nd?.operation_type === 'transfer') return false;
      return true;
    });
  }, [preview, inClusterRowIds]);

  const categoriesQuery = useQuery({ queryKey: ['categories'], queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const debtPartnersQuery = useQuery({ queryKey: ['debt-partners'], queryFn: getDebtPartners });
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });

  const opts = useMemo(
    () => ({
      categories: (categoriesQuery.data ?? []).map((c) => ({
        value: String(c.id), label: c.name, kind: c.kind, hint: c.kind === 'income' ? 'доход' : undefined,
      })),
      counterparties: (counterpartiesQuery.data ?? []).map((c) => ({ value: String(c.id), label: c.name })),
      debtPartners: (debtPartnersQuery.data ?? []).map((p) => ({ value: String(p.id), label: p.name })),
      accounts: (accountsQuery.data ?? []).map((a) => ({ value: String(a.id), label: a.name })),
      accountsRaw: accountsQuery.data ?? [],
    }),
    [categoriesQuery.data, counterpartiesQuery.data, debtPartnersQuery.data, accountsQuery.data],
  );

  const [editingRow, setEditingRow] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(
    null,
  );
  const [splittingRow, setSplittingRow] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(
    null,
  );
  const [shown, setShown] = useState(20);

  if (!preview) return null;

  if (singles.length === 0) {
    return (
      <section className="surface-card p-8 text-center">
        <p className="text-sm text-ink-2">
          Все строки распределены по группам — проверь карточки сверху и нажми «Импортировать готовые».
        </p>
      </section>
    );
  }

  return (
    <section className="surface-card overflow-hidden">
      <header className="flex items-start justify-between gap-3 px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Требуют твоего внимания{' '}
            <span className="font-normal text-ink-3">· {singles.length}</span>
          </h3>
          <p className="mt-0.5 text-xs text-ink-3">
            Выбери тип операции, категорию и подтверди — или отложи.
          </p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-ink-3 transition hover:bg-bg-surface2 hover:text-ink"
        >
          <Filter className="size-3" /> Фильтр
        </button>
      </header>

      <div>
        {singles.slice(0, shown).map((row) => (
          <TxRow
            key={row.id}
            row={row}
            options={opts}
            onEditDeep={(origin) => setEditingRow({ row, origin })}
            onSplitOpen={(origin) => setSplittingRow({ row, origin })}
          />
        ))}
      </div>

      {singles.length > shown ? (
        <footer className="flex items-center justify-between border-t border-line bg-bg-surface2 px-5 py-3.5">
          <span className="text-xs text-ink-3">
            Показано {shown} из {singles.length} одиночных операций
          </span>
          <button
            type="button"
            onClick={() => setShown((v) => v + 20)}
            className="rounded-lg border border-line bg-bg-surface px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-bg-surface2"
          >
            Показать ещё {Math.min(20, singles.length - shown)} →
          </button>
        </footer>
      ) : null}

      {editingRow ? (
        <EditTxRazvorot
          sessionId={sessionId}
          row={editingRow.row}
          origin={editingRow.origin}
          options={opts}
          onClose={() => setEditingRow(null)}
        />
      ) : null}

      {splittingRow ? (
        <SplitModal
          row={splittingRow.row}
          origin={splittingRow.origin}
          options={{ categories: opts.categories }}
          onClose={() => setSplittingRow(null)}
        />
      ) : null}
    </section>
  );
}
