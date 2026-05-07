'use client';

/**
 * ChronologicalView — flat list of all operations of the active session,
 * sorted by transaction_date DESC.
 *
 * Replacement for the cluster+attention split when the user prefers a
 * "leaf through the statement" workflow over abstract cluster cards.
 * Brand recognition still works — TxRow renders the inline «Это X?»
 * prompt where the resolver matched a brand.
 *
 * Visibility filter (matches current product behavior — see AttentionFeed):
 *   show     ready, warning, error rows
 *   hide     committed / duplicate / parked / skipped (terminal states)
 *   hide     transfer rows (kept in the «Переводы и дубли» widget)
 *
 * No account grouping (per user feedback) — single flat list across the
 * session. Backend is unchanged: data comes from the existing
 * `preview.rows` payload; sorting is client-side.
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
import type { ImportPreviewResponse, ImportPreviewRow } from '@/types/import';

const PAGE_STEP = 50;


function _isHiddenStatus(status: string | undefined | null): boolean {
  return (
    status === 'committed'
    || status === 'duplicate'
    || status === 'parked'
    || status === 'skipped'
  );
}


export function ChronologicalView({
  sessionId,
  preview,
  rows: explicitRows,
}: {
  /** Fallback session id used by TxRow when a row doesn't carry its own
   * (legacy single-session preview). Queue mode passes any value;
   * `row.session_id` overrides it per-row. */
  sessionId: number;
  /** Legacy single-session preview payload. Ignored when `rows` is set. */
  preview: ImportPreviewResponse | null;
  /** Queue-mode flat row list (cross-session, v1.23). When provided,
   * takes priority over `preview.rows`. */
  rows?: ImportPreviewRow[];
}) {
  const rows = useMemo<ImportPreviewRow[]>(() => {
    const source: ImportPreviewRow[] = explicitRows ?? preview?.rows ?? [];
    const visible = source.filter((r) => {
      if (_isHiddenStatus(r.status)) return false;
      const nd = r.normalized_data as Record<string, unknown> | undefined;
      // Transfer rows live in their own widget («Переводы и дубли»).
      // Same gating as AttentionFeed so we don't double-show them here.
      if (nd?.transfer_match) return false;
      if (nd?.operation_type === 'transfer') return false;
      return true;
    });
    // DESC by transaction_date — ISO strings sort lexicographically.
    return [...visible].sort((a, b) => {
      const ad = String((a.normalized_data as Record<string, unknown>)?.transaction_date
        ?? (a.normalized_data as Record<string, unknown>)?.date ?? '');
      const bd = String((b.normalized_data as Record<string, unknown>)?.transaction_date
        ?? (b.normalized_data as Record<string, unknown>)?.date ?? '');
      if (ad === bd) return b.id - a.id;
      return bd.localeCompare(ad);
    });
  }, [explicitRows, preview]);

  const categoriesQuery = useQuery({ queryKey: ['categories'], queryFn: () => getCategories() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const debtPartnersQuery = useQuery({ queryKey: ['debt-partners'], queryFn: getDebtPartners });
  const accountsQuery = useQuery({
    queryKey: ['accounts', 'with-closed'],
    queryFn: () => getAccounts({ includeClosed: true }),
  });

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

  const [editingRow, setEditingRow] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(null);
  const [splittingRow, setSplittingRow] = useState<{ row: ImportPreviewRow; origin: { x: number; y: number } } | null>(null);
  const [shown, setShown] = useState(PAGE_STEP);

  // Empty state: no preview AND no explicit rows → caller hasn't loaded anything.
  if (!preview && !explicitRows) return null;

  if (rows.length === 0) {
    return (
      <section className="surface-card p-8 text-center">
        <p className="text-sm text-ink-2">Нет операций для отображения.</p>
      </section>
    );
  }

  return (
    <section className="surface-card overflow-hidden">
      <header className="flex items-start justify-between gap-3 px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-ink">
            Все операции по дате{' '}
            <span className="font-normal text-ink-3">· {rows.length}</span>
          </h3>
          <p className="mt-0.5 text-xs text-ink-3">
            Самые свежие сверху. Подтверди бренд / категорию прямо в строке.
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
        {rows.slice(0, shown).map((row) => (
          <TxRow
            key={row.id}
            row={row}
            sessionId={sessionId}
            options={opts}
            onEditDeep={(origin) => setEditingRow({ row, origin })}
            onSplitOpen={(origin) => setSplittingRow({ row, origin })}
          />
        ))}
      </div>

      {rows.length > shown ? (
        <footer className="flex items-center justify-between border-t border-line bg-bg-surface2 px-5 py-3.5">
          <span className="text-xs text-ink-3">
            Показано {shown} из {rows.length} операций
          </span>
          <button
            type="button"
            onClick={() => setShown((v) => v + PAGE_STEP)}
            className="rounded-lg border border-line bg-bg-surface px-3 py-1.5 text-xs font-medium text-ink transition hover:bg-bg-surface2"
          >
            Показать ещё {Math.min(PAGE_STEP, rows.length - shown)} →
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
