"use client";

/**
 * Import moderation review panel — transaction-level feed (И-08 Phase 7+).
 *
 * Шаг от кластеров в сторону хронологической ленты: каждая ImportRow —
 * отдельная строка в ленте, отсортированная по дате. Метаданные модерации
 * (trust_zone, hypothesis, auto_trust) подтягиваются из /moderation-status
 * по cluster_row_ids → row.id. Кластер остаётся невидимой группировкой на
 * бэкенде, в UI его больше нет.
 *
 * Две секции:
 *   1. «Готово к импорту» — таблица строк, auto_trust=true.
 *   2. «Требуют твоего внимания» — карточки строк, всё остальное.
 */

import { memo, useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Loader2, Plus, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleChevron } from '@/components/ui/collapsible';
import { SearchSelect, type SearchSelectItem } from '@/components/ui/search-select';
import { ExpandableCard } from '@/components/dashboard-new/expandable-card';
import { CategoryDialog } from '@/components/categories/category-dialog';
import {
  attachRowToCounterparty,
  commitImport,
  excludeImportRow,
  getBulkClusters,
  getImportPreview,
  getModerationStatus,
  parkImportRow,
  startModeration,
  unexcludeImportRow,
  updateImportRow,
} from '@/lib/api/imports';
import { ClusterCard, type ClusterCardMeta } from '@/components/import/cluster-card';
import { AttachToCounterpartyButton } from '@/components/import/attach-counterparty';
import { getAccounts } from '@/lib/api/accounts';
import { createCategory, getCategories } from '@/lib/api/categories';
import { createCounterparty, getCounterparties } from '@/lib/api/counterparties';
import { createDebtPartner, getDebtPartners } from '@/lib/api/debt-partners';
import type { Account } from '@/types/account';
import type { Counterparty } from '@/types/counterparty';
import type {
  BulkClustersResponse,
  ClusterHypothesis,
  ModerationClusterEntry,
  ModerationStatusResponse,
  ImportPreviewResponse,
  ImportPreviewRow,
} from '@/types/import';
import type { Category, CreateCategoryPayload } from '@/types/category';

type Props = {
  sessionId: number;
  onClustersChanged?: () => void;
};

const ACTIVE_STATUSES = new Set(['pending', 'running']);

// Строка ленты — сырая ImportRow + привязанная мета-инфо от модератора.
type RefundMatchMeta = {
  partner_row_id: number;
  partner_date?: string | null;
  partner_description?: string | null;
  amount: string;
  confidence: number;
  reasons?: string[];
  side: 'expense' | 'income';
};

type FeedRow = {
  row: ImportPreviewRow;
  cluster: ModerationClusterEntry | null;
  date: string;
  amount: string;
  description: string;
  direction: 'income' | 'expense' | string;
  operationType: string;           // normalized_data.operation_type
  targetAccountId: number | null;  // normalized_data.target_account_id (для transfer)
  transferMatchMeta: any | null;   // normalized_data.transfer_match_meta (от TransferMatcher)
  refundMatch: RefundMatchMeta | null;  // normalized_data.refund_match (от RefundMatcher)
  isDuplicateSide: boolean;        // row.status === 'duplicate'
  isExcluded: boolean;             // row.status === 'skipped' (manually excluded)
  isDetachedFromCluster: boolean;  // normalized_data.detached_from_cluster — user kicked it out of a bulk cluster
};

export function ImportModerationPanel({ sessionId, onClustersChanged }: Props) {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ['imports', sessionId, 'moderation-status'],
    queryFn: () => getModerationStatus(sessionId),
    refetchInterval: (query) => {
      const data = query.state.data as ModerationStatusResponse | undefined;
      if (!data) return false;
      return ACTIVE_STATUSES.has(data.status) ? 2000 : false;
    },
  });

  // Mount timestamp for a grace window during which we poll preview even when
  // `summary.transfer_match` has not yet been set — the debounced matcher
  // writes the flag a moment after build_preview returns, so the very first
  // GET may land before the pending record exists.
  const previewMountedAtRef = useRef<number>(Date.now());
  if (previewMountedAtRef.current === 0) previewMountedAtRef.current = Date.now();

  const previewQuery = useQuery({
    queryKey: ['imports', sessionId, 'preview'],
    queryFn: () => getImportPreview(sessionId),
    // Keep refetching while the global transfer matcher is in-flight, so the
    // "Переводы и дубли" block fills in without a manual reload.
    refetchInterval: (query) => {
      const data = query.state.data as ImportPreviewResponse | undefined;
      const summary = (data?.summary ?? {}) as Record<string, any>;
      const tm = (summary.transfer_match ?? {}) as Record<string, any>;
      const tmStatus = typeof tm.status === 'string' ? tm.status : null;
      if (tmStatus === 'pending' || tmStatus === 'running') return 2000;
      if (tmStatus === 'ready' || tmStatus === 'failed') return false;
      // No flag yet — poll for up to 15 seconds after mount so we catch
      // the matcher's status write even if it lands after the first response.
      const grace = Date.now() - previewMountedAtRef.current < 15000;
      return grace ? 2000 : false;
    },
  });

  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: () => getCategories(),
  });

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: () => getAccounts(),
  });

  // Bulk-clusters (И-08 Этап 2/3): only fetched once moderation reached
  // preview-ready — clusters need normalized rows, which only exist after
  // build_preview. Refetched on preview/moderation-status invalidation so
  // a bulk-apply result immediately shrinks the card list.
  const bulkClustersQuery = useQuery({
    queryKey: ['imports', sessionId, 'bulk-clusters'],
    queryFn: () => getBulkClusters(sessionId),
    enabled: true,
  });

  const categoryById = useMemo(() => {
    const map = new Map<number, Category>();
    for (const cat of categoriesQuery.data ?? []) map.set(cat.id, cat);
    return map;
  }, [categoriesQuery.data]);

  const accountById = useMemo(() => {
    const map = new Map<number, Account>();
    for (const acc of accountsQuery.data ?? []) map.set(acc.id, acc);
    return map;
  }, [accountsQuery.data]);

  // Сборка ленты: row + привязанный кластер. Отсортировано по дате (desc).
  const feed = useMemo<FeedRow[]>(() => {
    const preview = previewQuery.data;
    const status = statusQuery.data;
    if (!preview) return [];

    const rowIdToCluster = new Map<number, ModerationClusterEntry>();
    for (const cluster of status?.clusters ?? []) {
      for (const rowId of cluster.cluster_row_ids) {
        rowIdToCluster.set(rowId, cluster);
      }
    }

    return preview.rows
      .filter((r) => r.status !== 'committed' && r.status !== 'parked')
      .map<FeedRow>((row) => {
        const n = (row.normalized_data || {}) as Record<string, any>;
        return {
          row,
          cluster: rowIdToCluster.get(row.id) ?? null,
          date: String(n.transaction_date ?? n.date ?? ''),
          amount: String(n.amount ?? '0'),
          description:
            String(n.description ?? n.original_description ?? '') ||
            row.raw_data?.description ||
            '—',
          direction: String(n.direction ?? 'expense') as FeedRow['direction'],
          operationType: String(n.operation_type ?? 'regular'),
          targetAccountId: n.target_account_id ? Number(n.target_account_id) : null,
          transferMatchMeta: n.transfer_match ?? null,
          refundMatch: (n.refund_match as RefundMatchMeta | null | undefined) ?? null,
          isDuplicateSide: row.status === 'duplicate',
          isExcluded: row.status === 'skipped',
          isDetachedFromCluster: Boolean(n.detached_from_cluster),
        };
      })
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [previewQuery.data, statusQuery.data]);

  const excludedFeed = feed.filter((f) => f.isExcluded);
  const activeFeed = feed.filter((f) => !f.isExcluded);

  // Row IDs that are already covered by a bulk-cluster card — user handles them
  // there (one click for the whole group). Remove them from the attention queue
  // so they don't show up twice.
  const bulkClusterRowIds = useMemo<Set<number>>(() => {
    const ids = new Set<number>();
    for (const c of bulkClustersQuery.data?.fingerprint_clusters ?? []) {
      for (const id of c.row_ids) ids.add(id);
    }
    return ids;
  }, [bulkClustersQuery.data]);

  // A row detached from a bulk cluster must ALWAYS land in the attention
  // feed — that's the contract of the "Исключить" action. Without this guard
  // a detached transfer row would get swallowed by the TransfersBucket and
  // disappear from view (the user's complaint, 2026-04-24). Detaching wins
  // over operation_type='transfer'.
  //
  // §12.1: a transfer without a known counter-account is NOT a real transfer
  // pair — it must not appear in the "Переводы и дубли" group (the matcher
  // failed to find its other side). It belongs in the attention feed so the
  // user sees the integrity error and decides: set the counter-account
  // manually, park, or exclude. Duplicate-side rows still pass through
  // because their own pair was already committed.
  const isCompleteTransfer = (f: FeedRow) =>
    f.operationType === 'transfer' && f.targetAccountId != null;
  const transferFeed = activeFeed.filter(
    (f) =>
      !f.isDetachedFromCluster &&
      !bulkClusterRowIds.has(f.row.id) &&
      (isCompleteTransfer(f) || f.isDuplicateSide),
  );
  const remainingFeed = activeFeed.filter(
    (f) =>
      (f.isDetachedFromCluster || (!isCompleteTransfer(f) && !f.isDuplicateSide)) &&
      !bulkClusterRowIds.has(f.row.id),
  );
  const isConfirmedOrAuto = (f: FeedRow) => f.cluster?.auto_trust === true || f.row.status === 'ready';
  // Confirmed rows go into their own tile (ExpandableCard), attention rows stay in the inline list.
  const confirmedFeed = remainingFeed.filter((f) => isConfirmedOrAuto(f))
    .sort((a, b) => b.date.localeCompare(a.date));
  const attentionFeed = remainingFeed.filter((f) => !isConfirmedOrAuto(f))
    .sort((a, b) => b.date.localeCompare(a.date));
  const attentionCount = attentionFeed.length;
  const confirmedCount = confirmedFeed.length;

  const startMutation = useMutation({
    mutationFn: () => startModeration(sessionId),
    onSuccess: () => {
      toast.success('Модератор запущен');
      queryClient.invalidateQueries({
        queryKey: ['imports', sessionId, 'moderation-status'],
      });
    },
    onError: (error: Error) => toast.error(`Не удалось запустить: ${error.message}`),
  });

  const commitMutation = useMutation({
    mutationFn: () => commitImport(sessionId, true),
    onSuccess: async (data) => {
      if (data.imported_count > 0) {
        toast.success(`Импортировано ${data.imported_count} транзакций`);
      } else {
        toast.info('Нет готовых транзакций для импорта');
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'preview'] }),
        queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'moderation-status'] }),
        queryClient.invalidateQueries({ queryKey: ['import-sessions'] }),
        queryClient.invalidateQueries({ queryKey: ['transactions'] }),
        queryClient.invalidateQueries({ queryKey: ['accounts'] }),
      ]);
      onClustersChanged?.();
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось импортировать'),
  });

  const readyCount =
    ((previewQuery.data?.summary as Record<string, any> | undefined)?.ready_rows as number | undefined) ?? 0;

  const status = statusQuery.data;
  const notStarted = !status || status.status === 'not_started';
  const isRunning = status?.status === 'running' || status?.status === 'pending';
  const isReady = status?.status === 'ready';
  const isFailed = status?.status === 'failed';
  const isSkipped = status?.status === 'skipped';

  const afterMutation = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'moderation-status'] });
    queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'preview'] });
    queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'bulk-clusters'] });
    onClustersChanged?.();
  }, [queryClient, sessionId, onClustersChanged]);

  const feedReady = status && (isReady || status.processed_clusters > 0) && feed.length > 0;

  return (
    <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
      <Header
        status={status}
        isRunning={isRunning}
        onStart={() => startMutation.mutate()}
        startPending={startMutation.isPending}
        readyCount={readyCount}
        onCommit={() => commitMutation.mutate()}
        commitPending={commitMutation.isPending}
      />

      <ModerationProgress status={status} />

      {isFailed && status?.error ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>Модератор упал: {status.error}</span>
        </div>
      ) : null}

      {isSkipped ? (
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
          LLM-модератор отключён или недоступен — разбирай строки вручную.
        </div>
      ) : null}

      {notStarted && !isRunning ? (
        <p className="mt-4 text-sm text-slate-400">
          Модератор ещё не запущен. Жми «Запустить модератор» — система разберёт строки и предложит категории.
        </p>
      ) : null}

      {feedReady ? (
        <div className="mt-5 space-y-5">
          <AutomationGauge
            autoRows={confirmedCount + transferFeed.length}
            attentionRows={attentionCount}
          />

          <TransfersBucket rows={transferFeed} accountById={accountById} />

          <BulkClustersBucket
            sessionId={sessionId}
            bulkClusters={bulkClustersQuery.data}
            rows={previewQuery.data?.rows ?? []}
            categories={categoriesQuery.data ?? []}
            onApplied={afterMutation}
          />

          <ConfirmedBucket
            rows={confirmedFeed}
            categoryById={categoryById}
            accountById={accountById}
            sessionId={sessionId}
            bulkClusters={bulkClustersQuery.data}
            onAfterAction={afterMutation}
          />

          <AttentionBucket
            rows={attentionFeed}
            attentionCount={attentionCount}
            confirmedCount={0}
            categoryById={categoryById}
            accountById={accountById}
            sessionId={sessionId}
            bulkClusters={bulkClustersQuery.data}
            onAfterAction={afterMutation}
          />

          <ExcludedBucket rows={excludedFeed} onAfterAction={afterMutation} />
        </div>
      ) : null}
    </Card>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Header / progress / gauge — без изменений
// ───────────────────────────────────────────────────────────────────────────

function Header({
  status,
  isRunning,
  onStart,
  startPending,
  readyCount,
  onCommit,
  commitPending,
}: {
  status?: ModerationStatusResponse;
  isRunning: boolean;
  onStart: () => void;
  startPending: boolean;
  readyCount: number;
  onCommit: () => void;
  commitPending: boolean;
}) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Sparkles className="size-5 text-indigo-500" />
          Модератор импорта
        </h3>
        <p className="mt-1 text-sm text-slate-500">
          Что уверено на 99%+ — в «Готово к импорту». Остальное требует твоего внимания: выбери категорию или отложи.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          onClick={onCommit}
          disabled={commitPending || readyCount === 0}
          title={readyCount === 0 ? 'Подтверди категории в «Требуют внимания», чтобы появились готовые строки' : undefined}
        >
          {commitPending ? (
            <><Loader2 className="size-4 animate-spin" /> Импортируем…</>
          ) : (
            <>Импортировать готовые{readyCount > 0 ? ` (${readyCount})` : ''}</>
          )}
        </Button>
        {!isRunning && (
          <Button variant="secondary" onClick={onStart} disabled={startPending}>
            <Sparkles className="size-4" />
            {status && !['not_started', 'pending'].includes(status.status)
              ? 'Перезапустить'
              : 'Запустить модератор'}
          </Button>
        )}
      </div>
    </div>
  );
}

function ModerationProgress({ status }: { status?: ModerationStatusResponse }) {
  if (!status) return null;
  const total = status.total_clusters || 0;
  const processed = status.processed_clusters || 0;
  const pct = total === 0 ? 0 : Math.min(100, Math.round((processed / total) * 100));

  if (!ACTIVE_STATUSES.has(status.status) && status.status !== 'ready') return null;

  return (
    <div className="mt-4">
      <div className="mb-1.5 flex items-center gap-2 text-xs text-slate-500">
        {ACTIVE_STATUSES.has(status.status) ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <CheckCircle2 className="size-3.5 text-emerald-600" />
        )}
        <span>
          {processed} из {total} групп{' '}
          {ACTIVE_STATUSES.has(status.status) ? 'обработано' : 'готово'}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full bg-indigo-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function AutomationGauge({ autoRows, attentionRows }: { autoRows: number; attentionRows: number }) {
  const total = autoRows + attentionRows;
  const pct = total === 0 ? 0 : Math.round((autoRows / total) * 100);
  return (
    <div className="rounded-2xl border border-slate-100 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Автоматизация импорта</p>
          <p className="mt-1 text-2xl font-semibold text-slate-950 tabular-nums">{pct}%</p>
          <p className="mt-0.5 text-xs text-slate-500">
            {autoRows} из {total} строк идут автоматически
          </p>
        </div>
        <p className="max-w-xs text-right text-xs text-slate-500">
          Чем больше строк ты правильно размечаешь, тем больше система доверяет себе в следующий раз.
        </p>
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Bucket 0: Распознаны как переводы и дубли
// ───────────────────────────────────────────────────────────────────────────

function TransfersBucket({ rows, accountById }: { rows: FeedRow[]; accountById: Map<number, Account> }) {
  const [expanded, setExpanded] = useState(false);
  if (rows.length === 0) return null;

  const primaryRows = rows.filter((r) => !r.isDuplicateSide);
  const duplicateRows = rows.filter((r) => r.isDuplicateSide);
  const totalAmount = primaryRows.reduce((s, r) => s + Math.abs(Number(r.amount) || 0), 0);

  const summaryNode = (
    <div className="flex w-full items-start gap-3">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-indigo-500 text-white">
        <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4M16 17H4m0 0l4 4m-4-4l4-4"/>
        </svg>
      </div>
      <div className="flex-1">
        <p className="text-base font-semibold text-slate-950">Переводы и дубли</p>
        <p className="text-sm text-slate-600">
          {primaryRows.length} перевод{primaryRows.length !== 1 ? 'а' : ''} на {formatMoney(totalAmount)} · {duplicateRows.length} дубл{duplicateRows.length === 1 ? 'ь' : 'я'} — система распознала автоматически
        </p>
      </div>
    </div>
  );

  const collapsedNode = (
    <div className="flex w-full items-start gap-3">
      <div className="flex-1">{summaryNode}</div>
      <CollapsibleChevron open={expanded} className="size-4 shrink-0 self-center text-indigo-500" />
    </div>
  );

  const expandedNode = (
    <div className="flex flex-col gap-3">
      <div className="pr-10">
        {summaryNode}
      </div>
      <div
        className="overflow-y-auto rounded-2xl bg-white p-3 ring-1 ring-indigo-200"
        style={{ maxHeight: 'min(58vh, 600px)' }}
      >
        <table className="w-full text-sm table-fixed">
          <thead>
            <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
              <th className="px-2 py-2 w-14">Дата</th>
              <th className="px-2 py-2">Описание</th>
              <th className="px-2 py-2 w-44">Счета</th>
              <th className="px-2 py-2 text-right w-28">Сумма</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((feedRow) => (
              <TransferRow key={feedRow.row.id} feedRow={feedRow} accountById={accountById} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-400">
        Переводы между своими счетами создадутся как одна парная транзакция — вторая сторона уже учтена. Настоящие дубли (повтор одной и той же выписки) не импортируются повторно.
      </p>
    </div>
  );

  return (
    <div className="rounded-2xl border-2 border-indigo-200 bg-indigo-50 p-4">
      <ExpandableCard
        isOpen={expanded}
        onToggle={() => setExpanded((v) => !v)}
        expandedWidth="860px"
        collapsed={collapsedNode}
        expanded={expandedNode}
      />
    </div>
  );
}

function TransferRow({ feedRow, accountById }: { feedRow: FeedRow; accountById: Map<number, Account> }) {
  const { row, date, description, amount, direction, targetAccountId, isDuplicateSide, transferMatchMeta } = feedRow;

  const shortDesc = description.length > 55 ? description.slice(0, 55).trim() + '…' : description;

  const sourceId = (row.normalized_data as Record<string, any>)?.account_id
    ? Number((row.normalized_data as Record<string, any>).account_id)
    : null;
  const sourceName = sourceId ? (accountById.get(sourceId)?.name ?? `#${sourceId}`) : null;
  const targetName = targetAccountId
    ? (accountById.get(targetAccountId)?.name ?? `#${targetAccountId}`)
    : null;

  // A row marked duplicate-by-transfer-match (is_secondary) is NOT a real
  // duplicate — it's the income leg of an internal transfer whose expense leg
  // will auto-create it on commit. Show it as a proper transfer (source → target)
  // with a "учтётся как пара" hint, not as an opaque "Дубль".
  const isPairSecondary = !!transferMatchMeta && transferMatchMeta.is_secondary === true;
  const isRealDuplicate = isDuplicateSide && !isPairSecondary;

  // For the secondary (income) leg, target = THIS row's account, source = the paired account.
  const pairLabel = (() => {
    if (isPairSecondary) {
      const pairedName = transferMatchMeta?.matched_account_name as string | undefined;
      const thisName = sourceName;
      if (pairedName && thisName) return `${pairedName} → ${thisName}`;
      if (pairedName) return `${pairedName} → ${direction === 'income' ? 'этот счёт' : 'другой счёт'}`;
    }
    if (sourceName && targetName) return `${sourceName} → ${targetName}`;
    if (sourceName && targetAccountId) return `${sourceName} → счёт #${targetAccountId}`;
    if (targetName) return `→ ${targetName}`;
    return 'перевод между своими';
  })();

  const linkLabel = isRealDuplicate ? 'Дубль · другая сессия' : pairLabel;
  const linkClass = isRealDuplicate
    ? 'text-slate-400'
    : isPairSecondary
      ? 'text-indigo-500 font-medium'
      : 'text-indigo-700 font-medium';

  const rowClass = isRealDuplicate ? 'text-slate-400 italic' : 'text-slate-800';
  const amountClass = [
    'px-2 py-2 text-right tabular-nums',
    direction === 'income' ? 'text-emerald-600' : 'text-slate-900',
    isRealDuplicate ? 'line-through' : '',
  ].join(' ');

  const titleHint = isPairSecondary
    ? `${description}\n\nПеревод учтётся как пара — эта строка не создаст отдельную транзакцию.`
    : description;

  return (
    <tr className={rowClass}>
      <td className="px-2 py-2 tabular-nums">{formatDateShort(date)}</td>
      <td className="px-2 py-2 truncate" title={titleHint}>{shortDesc}</td>
      <td className={`px-2 py-2 text-xs ${linkClass}`}>{linkLabel}</td>
      <td className={amountClass}>
        {formatSignedAmount(amount, direction)}
      </td>
    </tr>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Bulk clusters — массовое подтверждение паттернов (И-08 Этап 2/3)
// ───────────────────────────────────────────────────────────────────────────

function BulkClustersBucket({
  sessionId,
  bulkClusters,
  rows,
  categories,
  onApplied,
}: {
  sessionId: number;
  bulkClusters: BulkClustersResponse | undefined;
  rows: ImportPreviewRow[];
  categories: Category[];
  onApplied: () => void;
}) {
  const rowsById = useMemo(() => {
    const map = new Map<number, ImportPreviewRow>();
    for (const r of rows) map.set(r.id, r);
    return map;
  }, [rows]);

  // Build cards, precedence (highest first):
  //   1. counterparty groups (Phase 3) — authoritative, beat brand and fingerprint
  //   2. brand clusters — group per-TT fingerprints by their first token
  //   3. standalone fingerprint clusters — no counterparty, no brand
  // Each fingerprint lands in exactly one card.
  const cards = useMemo<Array<{ key: string; meta: ClusterCardMeta }>>(() => {
    if (!bulkClusters) return [];
    const fpById = new Map<string, typeof bulkClusters.fingerprint_clusters[number]>();
    for (const c of bulkClusters.fingerprint_clusters) fpById.set(c.fingerprint, c);

    const covered = new Set<string>();
    const result: Array<{ key: string; meta: ClusterCardMeta }> = [];

    for (const group of bulkClusters.counterparty_groups ?? []) {
      const members = group.fingerprint_cluster_ids
        .map((id) => fpById.get(id))
        .filter((m): m is typeof bulkClusters.fingerprint_clusters[number] => !!m);
      if (members.length === 0) continue;
      for (const m of members) covered.add(m.fingerprint);
      result.push({
        key: `cp:${group.counterparty_id}:${group.direction}`,
        meta: {
          kind: 'counterparty',
          counterpartyId: group.counterparty_id,
          counterpartyName: group.counterparty_name,
          direction: group.direction,
          count: group.count,
          totalAmount: group.total_amount,
          members,
        },
      });
    }

    for (const brand of bulkClusters.brand_clusters) {
      const members = brand.fingerprint_cluster_ids
        .map((id) => fpById.get(id))
        .filter((m): m is typeof bulkClusters.fingerprint_clusters[number] => !!m)
        .filter((m) => !covered.has(m.fingerprint));
      if (members.length === 0) continue;
      for (const m of members) covered.add(m.fingerprint);
      result.push({
        key: `brand:${brand.brand}:${brand.direction}`,
        meta: {
          kind: 'brand',
          brand: brand.brand,
          direction: brand.direction,
          count: brand.count,
          totalAmount: brand.total_amount,
          members,
        },
      });
    }

    const standalone = bulkClusters.fingerprint_clusters.filter(
      (c) => !covered.has(c.fingerprint),
    );
    for (const c of standalone) {
      result.push({
        key: `fp:${c.fingerprint}`,
        meta: { kind: 'fingerprint', cluster: c },
      });
    }
    return result;
  }, [bulkClusters]);

  if (!bulkClusters || cards.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-base font-semibold text-slate-900">
          Группы похожих операций ({cards.length})
        </p>
        <p className="text-xs text-slate-500">
          Подтверди сразу весь паттерн одним действием
        </p>
      </div>
      <div className="space-y-2">
        <AnimatePresence initial={false}>
          {cards.map((card, index) => (
            <motion.div
              key={card.key}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0, transition: { delay: Math.min(index, 10) * 0.02 } }}
              exit={{ opacity: 0, x: 24, transition: { duration: 0.14 } }}
            >
              <ClusterCard
                meta={card.meta}
                sessionId={sessionId}
                rowsById={rowsById}
                categories={categories}
                bulkClusters={bulkClusters}
                onApplied={onApplied}
              />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Единая лента: требующие внимания + проверенные/auto-trust (collapsed)
// ───────────────────────────────────────────────────────────────────────────

function AttentionBucket({
  rows,
  attentionCount,
  confirmedCount,
  categoryById,
  accountById,
  sessionId,
  bulkClusters,
  onAfterAction,
}: {
  rows: FeedRow[];
  attentionCount: number;
  confirmedCount: number;
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  sessionId: number;
  bulkClusters: BulkClustersResponse | undefined;
  onAfterAction: () => void;
}) {
  // Confirmed rows now live in their own ConfirmedBucket tile, so if there's
  // nothing here, just render nothing — the confirmed tile already communicates
  // completion state via its count.
  if (rows.length === 0) return null;

  const headerLabel = `Требуют твоего внимания (${attentionCount})`;
  const subLabel = 'Выбери категорию, подтверди или отложи';

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-base font-semibold text-slate-900">{headerLabel}</p>
        <p className="text-xs text-slate-500">{subLabel}</p>
      </div>
      {rows.length <= VIRTUAL_LIST_THRESHOLD ? (
        <div className="space-y-2">
          <AnimatePresence initial={false}>
            {rows.map((feedRow) => (
              <motion.div
                key={feedRow.row.id}
                layout
                initial={false}
                exit={{ opacity: 0, x: 24, height: 0, marginTop: 0, transition: { duration: 0.18 } }}
                transition={{ layout: { duration: 0.22, ease: 'easeOut' } }}
                style={{ overflow: 'hidden' }}
              >
                <AttentionCard
                  feedRow={feedRow}
                  categoryById={categoryById}
                  accountById={accountById}
                  sessionId={sessionId}
                  bulkClusters={bulkClusters}
                  onAfterAction={onAfterAction}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      ) : (
        <VirtualAttentionList
          rows={rows}
          categoryById={categoryById}
          accountById={accountById}
          sessionId={sessionId}
          bulkClusters={bulkClusters}
          onAfterAction={onAfterAction}
        />
      )}
    </div>
  );
}

// Below this threshold we render the plain list — virtualization has its own
// overhead (scroll-margin math, measureElement ResizeObservers) that is not
// worth paying for short sessions. Raised to 120 because the plain list is
// the only path with a proper AnimatePresence+layout animation on confirm;
// the virtualized path can only fall back to a CSS transform transition,
// which measureElement re-measures clobber after each confirm. Typical
// statements run 30–100 rows — keeping those on the animated path is the
// right trade-off, and the virtualized branch is left for edge-case
// mega-imports (several hundred rows) where animation quality matters less.
const VIRTUAL_LIST_THRESHOLD = 120;

function VirtualAttentionList({
  rows,
  categoryById,
  accountById,
  sessionId,
  bulkClusters,
  onAfterAction,
}: {
  rows: FeedRow[];
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  sessionId: number;
  bulkClusters: BulkClustersResponse | undefined;
  onAfterAction: () => void;
}) {
  const parentRef = useRef<HTMLDivElement | null>(null);
  const [scrollMargin, setScrollMargin] = useState(0);

  // useWindowVirtualizer needs the parent's offsetTop as scrollMargin so it
  // knows where this list starts in the document. Recompute on layout changes
  // (sections above this one can collapse/expand and shift the offset).
  useLayoutEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    const update = () => setScrollMargin(el.getBoundingClientRect().top + window.scrollY);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(document.body);
    window.addEventListener('resize', update);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', update);
    };
  }, []);

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => 160,
    overscan: 4,
    scrollMargin,
  });

  const items = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  return (
    <div ref={parentRef} style={{ position: 'relative', height: totalSize }}>
      {items.map((virtualRow) => {
        const feedRow = rows[virtualRow.index];
        return (
          <div
            key={feedRow.row.id}
            data-index={virtualRow.index}
            ref={virtualizer.measureElement}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${virtualRow.start - scrollMargin}px)`,
              transition: 'transform 220ms cubic-bezier(0.22, 1, 0.36, 1)',
              paddingBottom: 8,
            }}
          >
            <AttentionCard
              feedRow={feedRow}
              categoryById={categoryById}
              accountById={accountById}
              sessionId={sessionId}
              bulkClusters={bulkClusters}
              onAfterAction={onAfterAction}
            />
          </div>
        );
      })}
    </div>
  );
}

function AttentionCardImpl({
  feedRow,
  categoryById,
  accountById,
  sessionId,
  bulkClusters,
  onAfterAction,
}: {
  feedRow: FeedRow;
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  sessionId: number;
  bulkClusters: BulkClustersResponse | undefined;
  onAfterAction: () => void;
}) {
  const { row, cluster, date, description, amount, direction, refundMatch } = feedRow;
  const isAutoTrust = cluster?.auto_trust === true;
  const isConfirmed = row.status === 'ready';
  // Auto-trust rows start collapsed; confirmed rows also collapse after apply.
  const [collapsed, setCollapsed] = useState(isAutoTrust);
  const zone = cluster?.trust_zone ?? 'yellow';
  const zoneClass: Record<string, string> = {
    yellow: 'border-slate-200 bg-white',
    red: 'border-slate-200 bg-white',
    green: 'border-slate-200 bg-white',
  };
  // Row-level category from normalized_data is the strongest signal (rule
  // already matched or backend-resolved), so it takes priority over
  // cluster-level hints. Otherwise a refund matched by the cross-session
  // matcher won't surface its category in the UI — the cluster hasn't
  // learned a rule yet, but the row already knows its answer.
  const rowLevelCatId = (() => {
    const v = (row.normalized_data as Record<string, any> | undefined)?.category_id;
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  })();
  const suggestedCatId =
    rowLevelCatId ??
    cluster?.candidate_category_id ??
    cluster?.hypothesis?.predicted_category_id ??
    cluster?.global_pattern_category_id ??
    cluster?.bank_mechanics_category_id ??
    cluster?.account_context_category_id ??
    null;

  // ── Тип операции ────────────────────────────────────────────────────────────
  // direction (income/expense) — знак суммы из парсера, пользователь не меняет.
  // mainOp — верхний уровень классификации (что это за операция).
  // Под-выборы:  debtDir / investDir / creditKind — уточнение внутри типа.
  // credit_payment требует также суммы тела и процентов.
  type MainOp = 'regular' | 'transfer' | 'debt' | 'refund' | 'investment' | 'credit_operation';
  type DebtDir = 'lent' | 'borrowed' | 'repaid' | 'collected';
  type InvestDir = 'buy' | 'sell';
  type CreditKind = 'disbursement' | 'payment' | 'early_repayment';

  // Инициализация: пробуем угадать из hypothesis LLM.
  function llmToMainOp(op: string | undefined): MainOp {
    if (!op) return 'regular';
    if (op === 'regular' || op === 'refund' || op === 'transfer' || op === 'debt') return op as MainOp;
    if (op === 'investment_buy' || op === 'investment_sell') return 'investment';
    if (op === 'credit_disbursement' || op === 'credit_payment' || op === 'credit_early_repayment') return 'credit_operation';
    return 'regular';
  }
  function llmToCreditKind(op: string | undefined): CreditKind {
    if (op === 'credit_payment') return 'payment';
    if (op === 'credit_early_repayment') return 'early_repayment';
    return 'disbursement';
  }
  function llmToInvestDir(op: string | undefined): InvestDir {
    return op === 'investment_sell' ? 'sell' : 'buy';
  }

  // LLM hypothesis в приоритете ТОЛЬКО когда модель уверена. Если модель
  // задала follow_up_question или вернула confidence < 0.7 — её гипотеза
  // ненадёжная и не должна перебивать детерминистическую Layer 2 (банковскую
  // механику). Без этого Яндекс «отмена / возврат» приходила в дропдаун как
  // "Обычная", потому что LLM попросил уточнение, а его operation_type='regular'
  // молча выигрывал у Layer 2 'refund'.
  const llmHypo = cluster?.hypothesis;
  const llmConfident =
    !!llmHypo &&
    !llmHypo.follow_up_question &&
    (llmHypo.confidence == null || llmHypo.confidence >= 0.7);
  const llmOp = llmConfident ? llmHypo?.operation_type : undefined;
  // Priority: confident LLM → Layer 2 bank mechanics → Layer 1 account context →
  // refund matcher (in-session pair: same amount, opposite direction).
  // Refund matcher выставляет 'refund' только для income-стороны пары — это и
  // есть «возврат денег». Expense-сторона остаётся regular (исходная покупка),
  // под ней покажем hint про найденную пару.
  const refundOp = refundMatch?.side === 'income' ? 'refund' : undefined;
  const contextOp =
    cluster?.bank_mechanics_operation_type ??
    cluster?.account_context_operation_type ??
    refundOp;
  const [mainOp, setMainOp] = useState<MainOp>(llmToMainOp(llmOp ?? contextOp));
  const [debtDir, setDebtDir] = useState<DebtDir>('borrowed');
  const [investDir, setInvestDir] = useState<InvestDir>(llmToInvestDir(llmOp));
  const [creditKind, setCreditKind] = useState<CreditKind>(llmToCreditKind(llmOp));
  const [creditPrincipal, setCreditPrincipal] = useState<string>('');
  const [creditInterest, setCreditInterest] = useState<string>('');
  const [pickedCatId, setPickedCatId] = useState<number | null>(suggestedCatId);
  // Credit account (for credit_payment / disbursement / early_repayment) +
  // target account (for transfer). Initialized from normalized_data so re-opens
  // of an already-confirmed row preserve the user's prior choice.
  const initialCreditAccountId = (() => {
    const v = (row.normalized_data as Record<string, any> | undefined)?.credit_account_id;
    return v ? Number(v) : null;
  })();
  const initialTargetAccountId = (() => {
    const v = (row.normalized_data as Record<string, any> | undefined)?.target_account_id;
    return v ? Number(v) : null;
  })();
  const [pickedCreditAccountId, setPickedCreditAccountId] = useState<number | null>(initialCreditAccountId);
  const [pickedTargetAccountId, setPickedTargetAccountId] = useState<number | null>(initialTargetAccountId);
  const initialDebtPartnerId = (() => {
    const v = (row.normalized_data as Record<string, any> | undefined)?.debt_partner_id;
    return v ? Number(v) : null;
  })();
  const [pickedDebtPartnerId, setPickedDebtPartnerId] = useState<number | null>(initialDebtPartnerId);
  const debtPartnersQuery = useQuery({ queryKey: ['debt-partners'], queryFn: getDebtPartners });
  const debtPartners = debtPartnersQuery.data ?? [];
  const debtPartnerQueryClient = useQueryClient();
  const createDebtPartnerMutation = useMutation({
    mutationFn: (name: string) =>
      createDebtPartner({
        name,
        // Pick the opening-balance kind from the debt direction — a new
        // partner created while logging "я одолжил" should start as
        // receivable (they owe me); "мне заняли" → payable.
        opening_balance_kind:
          debtDir === 'borrowed' || debtDir === 'repaid' ? 'payable' : 'receivable',
      }),
    onSuccess: (created) => {
      debtPartnerQueryClient.invalidateQueries({ queryKey: ['debt-partners'] });
      setPickedDebtPartnerId(created.id);
      toast.success(`Создан: ${created.name}`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать'),
  });

  const creditAccounts = useMemo(
    () => Array.from(accountById.values()).filter((a) => a.is_credit || a.account_type === 'credit' || a.account_type === 'credit_card' || a.account_type === 'installment_card'),
    [accountById],
  );
  const transferAccounts = useMemo(
    () => Array.from(accountById.values()).sort((a, b) => a.name.localeCompare(b.name, 'ru')),
    [accountById],
  );

  // ── Разбивка на части (split) ──────────────────────────────────────────────
  // Каждая часть — мини-транзакция со своим типом, суммой и нужными полями.
  // Сумма частей должна точно совпадать с суммой исходной строки.
  type SplitPart = {
    operation_type: 'regular' | 'transfer' | 'refund' | 'debt';
    amount: string;
    category_id: number | null;
    target_account_id: number | null;
    debt_direction: 'borrowed' | 'lent' | 'repaid' | 'collected';
    debt_partner_id: number | null;
    description: string;
  };
  const emptyPart = (): SplitPart => ({
    operation_type: 'regular',
    amount: '',
    category_id: null,
    target_account_id: null,
    debt_direction: 'borrowed',
    debt_partner_id: null,
    description: '',
  });
  const [splitOpen, setSplitOpen] = useState<boolean>(false);
  const [splitParts, setSplitParts] = useState<SplitPart[]>(() => [emptyPart(), emptyPart()]);
  const totalAmount = Math.abs(parseFloat(amount.replace(',', '.')) || 0);
  const splitSum = splitParts.reduce((acc, p) => acc + (parseFloat(p.amount.replace(',', '.')) || 0), 0);
  const splitRemaining = +(totalAmount - splitSum).toFixed(2);
  const splitValid = splitOpen && splitParts.length >= 2 && Math.abs(splitRemaining) < 0.01 && splitParts.every((p) => {
    const amt = parseFloat(p.amount.replace(',', '.')) || 0;
    if (amt <= 0) return false;
    if ((p.operation_type === 'regular' || p.operation_type === 'refund') && !p.category_id) return false;
    if (p.operation_type === 'transfer' && !p.target_account_id) return false;
    if (p.operation_type === 'debt' && !p.debt_partner_id) return false;
    return true;
  });

  // Cluster meta (hypothesis + L1/L2 hints) приходит из /moderation-status
  // отдельным запросом, обычно ПОЗЖЕ первого рендера карточки. useState-инициализатор
  // отрабатывает один раз на пустых данных и оставляет mainOp='regular',
  // pickedCatId=null. Догоняем подсказки одноразово, как только они появились;
  // флаг гарантирует, что повторные ре-фетчи не перезатирают выбор пользователя.
  const appliedSuggestionRef = useRef(false);
  useEffect(() => {
    if (appliedSuggestionRef.current) return;
    const nextOp = llmOp ?? contextOp;
    if (!nextOp && suggestedCatId == null) return;
    if (nextOp) {
      setMainOp(llmToMainOp(nextOp));
      setInvestDir(llmToInvestDir(nextOp));
      setCreditKind(llmToCreditKind(nextOp));
    }
    if (suggestedCatId != null) setPickedCatId(suggestedCatId);
    appliedSuggestionRef.current = true;
  }, [llmOp, contextOp, suggestedCatId]);

  // Итоговый operation_type, который уйдёт на backend.
  const actualOpType: string = (() => {
    switch (mainOp) {
      case 'regular': return 'regular';
      case 'transfer': return 'transfer';
      case 'debt': return 'debt';
      case 'refund': return 'refund';
      case 'investment': return investDir === 'sell' ? 'investment_sell' : 'investment_buy';
      case 'credit_operation':
        if (creditKind === 'payment') return 'credit_payment';
        if (creditKind === 'early_repayment') return 'credit_early_repayment';
        return 'credit_disbursement';
    }
  })();

  // Нужна ли выборка категории? Для долга — нет: вместо категории там
  // дебитор / кредитор (DebtPartner), а не бюджетная статья.
  const needsCategory = mainOp === 'regular' || mainOp === 'refund';
  const needsDebtPartner = mainOp === 'debt';
  // Для возврата категория — всегда доходная.
  const kindFilter: 'income' | 'expense' =
    mainOp === 'refund' ? 'expense' : direction === 'income' ? 'income' : 'expense';

  const availableCategories = useMemo(() => {
    if (!needsCategory) return [];
    return Array.from(categoryById.values())
      .filter((c) => c.kind === kindFilter)
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'));
  }, [categoryById, kindFilter, needsCategory]);

  useEffect(() => {
    if (!pickedCatId) return;
    const cat = categoryById.get(pickedCatId);
    if (!cat || cat.kind !== kindFilter) setPickedCatId(null);
  }, [kindFilter, pickedCatId, categoryById]);

  const parkMutation = useMutation({
    mutationFn: () => parkImportRow(row.id),
    onSuccess: () => { toast.success(`Отложено #${row.row_index}`); onAfterAction(); },
    onError: (error: Error) => toast.error(`Не удалось отложить: ${error.message}`),
  });

  const excludeMutation = useMutation({
    mutationFn: () => excludeImportRow(row.id),
    onSuccess: () => { toast.success(`Исключено #${row.row_index}`); onAfterAction(); },
    onError: (error: Error) => toast.error(`Не удалось исключить: ${error.message}`),
  });

  const [attachPickerOpen, setAttachPickerOpen] = useState(false);
  const attachMutation = useMutation({
    mutationFn: (cp: { id: number; name: string }) =>
      attachRowToCounterparty(sessionId, row.id, cp.id).then((data) => ({ ...data, _cpName: cp.name })),
    onSuccess: (data) => {
      setAttachPickerOpen(false);
      toast.success(`Добавлено к контрагенту «${data._cpName}»`);
      onAfterAction();
    },
    onError: (error: Error) => toast.error(`Не удалось добавить: ${error.message}`),
  });

  // У строки есть «черновик» разбивки, если в state хоть одна часть имеет
  // непустую сумму. Это не зависит от того, открыта ли модалка.
  const hasSplitDraft = splitParts.some((p) => p.amount && parseFloat(p.amount.replace(',', '.')) > 0);

  // Проверяем готовность «Применить»:
  const canApply = (() => {
    // Split-режим: если разбивка введена — обязательно валидной должна быть.
    if (hasSplitDraft) return splitValid;
    if (mainOp === 'regular' || mainOp === 'refund') return Boolean(pickedCatId);
    if (mainOp === 'debt') return Boolean(pickedDebtPartnerId);
    if (mainOp === 'transfer') return Boolean(pickedTargetAccountId);
    if (mainOp === 'credit_operation') {
      if (!pickedCreditAccountId) return false;
      if (creditKind === 'payment') {
        const p = parseFloat(creditPrincipal.replace(',', '.'));
        const i = parseFloat(creditInterest.replace(',', '.'));
        return Number.isFinite(p) && p >= 0 && Number.isFinite(i) && i >= 0;
      }
      return true;
    }
    // investment — применяем всегда
    return true;
  })();

  const applyMutation = useMutation({
    mutationFn: async () => {
      // Split mode: отправляем разбивку. Сама строка остаётся regular —
      // backend на коммите создаст N транзакций по частям, каждая со своим типом.
      if (hasSplitDraft) {
        const payload: Record<string, unknown> = {
          type: direction,
          operation_type: 'regular',
          action: 'confirm',
          split_items: splitParts.map((p) => ({
            operation_type: p.operation_type,
            amount: parseFloat(p.amount.replace(',', '.')) || 0,
            category_id: p.operation_type === 'debt' ? null : p.category_id,
            target_account_id: p.target_account_id,
            debt_direction: p.operation_type === 'debt' ? p.debt_direction : null,
            debt_partner_id: p.operation_type === 'debt' ? p.debt_partner_id : null,
            description: p.description || null,
          })),
        };
        await updateImportRow(row.id, payload);
        return;
      }
      const payload: Record<string, unknown> = {
        type: mainOp === 'refund' ? 'income' : direction,
        operation_type: actualOpType,
        action: 'confirm',
      };
      if (needsCategory) payload.category_id = pickedCatId;
      if (mainOp === 'debt') {
        payload.debt_direction = debtDir;
        payload.debt_partner_id = pickedDebtPartnerId;
      }
      if (mainOp === 'transfer') payload.target_account_id = pickedTargetAccountId;
      if (mainOp === 'credit_operation') {
        payload.credit_account_id = pickedCreditAccountId;
        if (creditKind === 'payment') {
          payload.credit_principal_amount = parseFloat(creditPrincipal.replace(',', '.')) || 0;
          payload.credit_interest_amount = parseFloat(creditInterest.replace(',', '.')) || 0;
        }
      }
      await updateImportRow(row.id, payload);
    },
    onSuccess: () => {
      toast.success(`Применено к строке #${row.row_index}`);
      setCollapsed(true);
      onAfterAction();
    },
    onError: (error: Error) => toast.error(`Не удалось применить: ${error.message}`),
  });

  // Shorten pathologically long parser-mangled descriptions — keep ≤ 100 chars
  // to fight PDF-extract noise like "Договора Оплата товаров и услуг...11 361,00 ₽ 11 361,00 ₽..."
  const displayDescription =
    description.length > 100 ? description.slice(0, 100).trim() + '…' : description;

  // ── Compact (collapsed) view for confirmed / auto-trust rows ─────────────
  if (collapsed) {
    const catId =
      cluster?.candidate_category_id ?? cluster?.hypothesis?.predicted_category_id ?? pickedCatId ?? null;
    const catName = catId ? categoryById.get(catId)?.name ?? '—' : '—';
    const badgeText = isConfirmed && !isAutoTrust ? '✓ Проверено' : '✓ Авто';
    const badgeClass = isConfirmed && !isAutoTrust
      ? 'bg-indigo-100 text-indigo-700'
      : 'bg-emerald-100 text-emerald-700';
    const borderClass = isConfirmed && !isAutoTrust
      ? 'border-indigo-200 bg-indigo-50/40'
      : 'border-emerald-200 bg-emerald-50/40';
    return (
      <div className={`overflow-hidden rounded-2xl border p-2.5 ${borderClass}`}>
        <div className="flex items-center gap-3">
          <span className="shrink-0 w-12 text-xs font-medium tabular-nums text-slate-500">
            {formatDateShort(date)}
          </span>
          <div className="min-w-0 flex-1 overflow-hidden">
            <p
              className="block w-full overflow-hidden text-ellipsis whitespace-nowrap text-sm font-medium text-slate-900"
              title={description}
            >
              {displayDescription}
            </p>
          </div>
          <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${badgeClass}`}>
            {badgeText}
          </span>
          <span className="inline-flex max-w-[10rem] shrink-0 truncate rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
            {catName}
          </span>
          <span className={`shrink-0 w-24 text-right text-sm font-semibold tabular-nums ${direction === 'income' ? 'text-emerald-600' : 'text-slate-900'}`}>
            {formatSignedAmount(amount, direction)}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setCollapsed(false)}
            title="Изменить разметку"
          >
            Изменить
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={`overflow-hidden rounded-2xl border p-3 ${
      isConfirmed ? 'border-indigo-200 bg-indigo-50/30' : (zoneClass[zone] ?? zoneClass.yellow)
    }`}>
      {/* Row 1: date + description + amount — компактная одна строка */}
      <div className="flex items-start gap-3">
        <span className="shrink-0 w-12 text-xs font-medium tabular-nums text-slate-500 pt-0.5">
          {formatDateShort(date)}
        </span>
        <div className="min-w-0 flex-1 overflow-hidden">
          <p
            className="block w-full overflow-hidden text-ellipsis whitespace-nowrap text-sm font-medium text-slate-900"
            title={description}
          >
            {displayDescription}
          </p>
          {cluster?.identifier_value ? (
            <p className="block w-full overflow-hidden text-ellipsis whitespace-nowrap text-xs text-slate-500">
              id {cluster.identifier_value}
            </p>
          ) : null}
        </div>
        <div className="shrink-0 flex items-center gap-2">
          {isConfirmed && (
            <span
              className="inline-flex items-center gap-0.5 rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-indigo-700"
              title="Эта строка уже проверена и подтверждена"
            >
              ✓ Проверено
            </span>
          )}
          <span
            className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
              direction === 'income'
                ? 'bg-emerald-100 text-emerald-700'
                : 'bg-slate-100 text-slate-600'
            }`}
            title={direction === 'income' ? 'Доход (определено парсером по знаку суммы)' : 'Расход (определено парсером по знаку суммы)'}
          >
            {direction === 'income' ? '↓ Доход' : '↑ Расход'}
          </span>
          <ZoneBadge zone={zone} />
          <span
            className={`text-sm font-semibold tabular-nums whitespace-nowrap ${
              direction === 'income' ? 'text-emerald-600' : 'text-slate-900'
            }`}
          >
            {formatSignedAmount(amount, direction)}
          </span>
        </div>
      </div>

      {/* Row 2: trust signal + (follow-up) */}
      <div className="mt-1 pl-14">
        <TrustSignal cluster={cluster} />
        <GlobalPatternHint cluster={cluster} />
        <BankMechanicsHint cluster={cluster} />
        <AccountContextHint cluster={cluster} />
        <RefundPairHint match={refundMatch} />
        {cluster?.hypothesis?.follow_up_question ? (
          <p className="mt-1.5 rounded-xl border border-amber-300 bg-white px-3 py-1.5 text-xs text-amber-900">
            ❓ {cluster.hypothesis.follow_up_question}
          </p>
        ) : null}
      </div>

      {/* Row 3: operation type + sub-pickers + (optional) category + actions */}
      <div className="mt-2 pl-14 flex flex-wrap items-center gap-2 rounded-xl bg-slate-50 px-2 py-2">
        {/* Главный тип */}
        <MainOpPicker value={mainOp} onChange={(v) => { setMainOp(v as typeof mainOp); setPickedCatId(null); }} />

        {/* Под-пикер: долг — направление */}
        {mainOp === 'debt' && (
          <SubPicker
            value={debtDir}
            onChange={(v) => setDebtDir(v as DebtDir)}
            options={[
              { value: 'borrowed', label: 'Мне заняли / взял' },
              { value: 'lent', label: 'Я одолжил' },
              { value: 'repaid', label: 'Я вернул долг' },
              { value: 'collected', label: 'Мне вернули' },
            ]}
          />
        )}

        {/* Дебитор / Кредитор — вместо категории для долга */}
        {needsDebtPartner && (
          <CompactSelect
            value={pickedDebtPartnerId != null ? String(pickedDebtPartnerId) : ''}
            onChange={(v) => setPickedDebtPartnerId(v ? Number(v) : null)}
            options={debtPartners.map((p) => ({ value: String(p.id), label: p.name }))}
            placeholder="— дебитор / кредитор —"
            widthClassName="w-52"
            ariaLabel="Дебитор или кредитор"
            createAction={{
              visible: !createDebtPartnerMutation.isPending,
              label: '',
              onClick: (name) => {
                if (name) createDebtPartnerMutation.mutate(name);
              },
            }}
          />
        )}

        {/* Под-пикер: инвестиция — покупка/продажа */}
        {mainOp === 'investment' && (
          <SubPicker
            value={investDir}
            onChange={(v) => setInvestDir(v as InvestDir)}
            options={[
              { value: 'buy', label: 'Покупка' },
              { value: 'sell', label: 'Продажа' },
            ]}
          />
        )}

        {/* Под-пикер: кредитная операция — вид */}
        {mainOp === 'credit_operation' && (
          <SubPicker
            value={creditKind}
            onChange={(v) => setCreditKind(v as CreditKind)}
            options={[
              { value: 'disbursement', label: 'Получение кредита' },
              { value: 'payment', label: 'Платёж по кредиту' },
              { value: 'early_repayment', label: 'Досрочное погашение' },
            ]}
          />
        )}

        {/* Поля суммы для платежа по кредиту */}
        {mainOp === 'credit_operation' && creditKind === 'payment' && (
          <>
            <input
              type="text"
              value={creditPrincipal}
              onChange={(e) => setCreditPrincipal(e.target.value)}
              placeholder="Тело долга, ₽"
              className="h-8 w-32 rounded-lg border border-slate-200 bg-white px-2 text-xs font-medium text-slate-900 shadow-sm outline-none focus:border-slate-400"
            />
            <input
              type="text"
              value={creditInterest}
              onChange={(e) => setCreditInterest(e.target.value)}
              placeholder="Проценты, ₽"
              className="h-8 w-28 rounded-lg border border-slate-200 bg-white px-2 text-xs font-medium text-slate-900 shadow-sm outline-none focus:border-slate-400"
            />
          </>
        )}

        {/* Категория — только для regular / debt / refund */}
        {needsCategory ? (
          <CategoryPicker
            value={pickedCatId}
            onChange={setPickedCatId}
            categories={availableCategories}
            kindHint={kindFilter}
          />
        ) : null}

        {/* Целевой счёт перевода */}
        {mainOp === 'transfer' && (
          <CompactSelect
            value={pickedTargetAccountId ? String(pickedTargetAccountId) : ''}
            onChange={(v) => setPickedTargetAccountId(v ? Number(v) : null)}
            options={transferAccounts.map((acc) => ({ value: String(acc.id), label: acc.name }))}
            placeholder="Куда перевод…"
            widthClassName="w-48"
            ariaLabel="Счёт назначения перевода"
          />
        )}

        {/* Кредитный счёт — для всех видов credit_operation */}
        {mainOp === 'credit_operation' && (
          <CompactSelect
            value={pickedCreditAccountId ? String(pickedCreditAccountId) : ''}
            onChange={(v) => setPickedCreditAccountId(v ? Number(v) : null)}
            options={creditAccounts.map((acc) => ({ value: String(acc.id), label: acc.name }))}
            placeholder={creditAccounts.length === 0 ? 'Нет кредитных счетов' : 'Какой кредит…'}
            widthClassName="w-56"
            ariaLabel="Кредитный счёт"
          />
        )}

        <div className="ml-auto flex items-center gap-1">
          <SplitButton
            active={splitOpen || splitParts.some((p) => p.amount)}
            onClick={() => setSplitOpen(true)}
          />
          <AttachToCounterpartyButton
            open={attachPickerOpen}
            setOpen={setAttachPickerOpen}
            bulkClusters={bulkClusters}
            sourceDirection={direction === 'income' ? 'income' : 'expense'}
            sourceAmount={totalAmount}
            sourceDescription={displayDescription}
            onAttach={(cp) => attachMutation.mutate(cp)}
            isPending={attachMutation.isPending}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => excludeMutation.mutate()}
            disabled={excludeMutation.isPending}
            title="Не импортировать эту строку"
          >
            Исключить
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => parkMutation.mutate()}
            disabled={parkMutation.isPending}
          >
            Отложить
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => applyMutation.mutate()}
            disabled={applyMutation.isPending || !canApply}
          >
            Применить
          </Button>
        </div>
      </div>

      {/* Если у строки уже есть валидная разбивка — показываем компактный
          summary вместо обычной (одной) категории, чтобы пользователь видел,
          что разбивка сохранена и готова к применению. */}
      {splitValid ? (
        <div className="mt-1.5 ml-14 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="font-semibold text-indigo-700">🔀 Разбито на {splitParts.length}:</span>
          {splitParts.map((p, i) => {
            const cat = p.category_id ? categoryById.get(p.category_id) : null;
            const tgt = p.target_account_id ? accountById.get(p.target_account_id) : null;
            const label = p.operation_type === 'transfer'
              ? `→ ${tgt?.name ?? 'счёт'}`
              : p.operation_type === 'debt'
                ? `Долг (${p.debt_direction})`
                : (cat?.name ?? '—');
            return (
              <span key={i} className="rounded-md bg-indigo-50 px-2 py-0.5 text-indigo-900">
                {p.amount} ₽ · {label}
              </span>
            );
          })}
        </div>
      ) : null}

      {/* Modal-портал с FLIP-анимацией из точки клика на иконку разбивки. */}
      <SplitModal
        isOpen={splitOpen}
        onClose={() => setSplitOpen(false)}
        sourceRow={{ amount: totalAmount, direction: direction === 'income' ? 'income' : 'expense', description: displayDescription }}
      >
        <SplitEditor
          parts={splitParts}
          setParts={setSplitParts}
          totalAmount={totalAmount}
          remaining={splitRemaining}
          direction={direction === 'income' ? 'income' : 'expense'}
          categoryById={categoryById}
          accountById={accountById}
          excludeAccountId={row.normalized_data?.account_id ? Number(row.normalized_data.account_id) : null}
        />
        <div className="mt-4 flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setSplitOpen(false)}
          >
            Готово
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!splitValid}
            onClick={() => setSplitOpen(false)}
            title={splitValid ? 'Сохранить разбивку и закрыть окно' : 'Сначала распредели всю сумму'}
          >
            Сохранить разбивку
          </Button>
        </div>
      </SplitModal>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Split icon button — стрелка с одним основанием и двумя вершинами
// ───────────────────────────────────────────────────────────────────────────

function SplitButton({ active, onClick }: { active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        // Save click coordinates so the modal can FLIP-animate from the icon
        // (not from screen center). Read by SplitModal on next render.
        (window as any).__lastSplitClick = { x: e.clientX, y: e.clientY };
        onClick();
      }}
      title="Разбить операцию на несколько с разными типами"
      className={`flex items-center justify-center h-8 w-8 rounded-md border transition ${
        active
          ? 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
          : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-700'
      }`}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="size-4">
        <path d="M12 22V12" />
        <path d="M12 12 L4 4" />
        <path d="M12 12 L20 4" />
        <path d="M2 4 L6 4 L6 8" />
        <path d="M22 4 L18 4 L18 8" />
      </svg>
    </button>
  );
}


// ───────────────────────────────────────────────────────────────────────────
// Split modal — FLIP-анимация из точки клика, как у дашборда expandable-card
// ───────────────────────────────────────────────────────────────────────────

function SplitModal({
  isOpen,
  onClose,
  sourceRow,
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  sourceRow: { amount: number; direction: 'income' | 'expense'; description: string };
  children: React.ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<'closed' | 'measure' | 'enter' | 'open' | 'exit'>('closed');
  const originRef = useRef<{ x: number; y: number } | null>(null);
  const DURATION = 320;
  const EASING = 'cubic-bezier(0.4, 0, 0.15, 1)';

  // Captures click coordinates at the moment the modal is opened — used as the
  // origin point for the FLIP animation. Falls back to viewport center.
  useEffect(() => {
    if (isOpen && phase === 'closed') {
      const lastClick = (window as any).__lastSplitClick as { x: number; y: number } | undefined;
      originRef.current = lastClick ?? { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      setPhase('measure');
    }
  }, [isOpen, phase]);

  useLayoutEffect(() => {
    if (phase !== 'measure') return;
    const panel = panelRef.current;
    const origin = originRef.current;
    if (!panel || !origin) return;
    panel.style.transition = 'none';
    panel.style.transform = 'translate(-50%, -50%) scale(1)';
    panel.style.opacity = '0';
    const rect = panel.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const dx = origin.x - centerX;
    const dy = origin.y - centerY;
    panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.05)`;
    panel.getBoundingClientRect();
    panel.style.transition = `transform ${DURATION}ms ${EASING}, opacity ${Math.round(DURATION * 0.6)}ms ease`;
    panel.style.transform = 'translate(-50%, -50%) scale(1)';
    panel.style.opacity = '1';
    setPhase('enter');
  }, [phase]);

  useEffect(() => {
    if (!isOpen && phase !== 'closed' && phase !== 'exit') {
      const panel = panelRef.current;
      const origin = originRef.current;
      if (!panel || !origin) {
        setPhase('closed');
        return;
      }
      const rect = panel.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      const dx = origin.x - centerX;
      const dy = origin.y - centerY;
      panel.style.transition = `transform ${DURATION}ms ${EASING}, opacity ${Math.round(DURATION * 0.5)}ms ease`;
      panel.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(0.05)`;
      panel.style.opacity = '0';
      setPhase('exit');
    }
  }, [isOpen, phase]);

  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent) => {
      if (e.propertyName !== 'transform') return;
      if (phase === 'enter') setPhase('open');
      if (phase === 'exit') setPhase('closed');
    },
    [phase],
  );

  useEffect(() => {
    if (phase !== 'exit') return;
    const t = setTimeout(() => setPhase('closed'), DURATION + 100);
    return () => clearTimeout(t);
  }, [phase]);

  useEffect(() => {
    if (phase === 'closed') return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    const sw = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.overflow = 'hidden';
    if (sw > 0) document.body.style.paddingRight = `${sw}px`;
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      document.body.style.paddingRight = '';
    };
  }, [phase, onClose]);

  if (phase === 'closed' || typeof document === 'undefined') return null;
  const backdropVisible = phase === 'enter' || phase === 'open';

  return createPortal(
    <>
      <div
        onClick={onClose}
        className="fixed inset-0 z-[100]"
        style={{
          backgroundColor: 'rgba(0,0,0,0.25)',
          opacity: backdropVisible ? 1 : 0,
          transition: `opacity ${DURATION}ms ease`,
        }}
      />
      <div
        ref={panelRef}
        onTransitionEnd={handleTransitionEnd}
        className="fixed left-1/2 top-1/2 z-[101] max-h-[85vh] w-[720px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-3xl bg-white p-6 shadow-[0_25px_80px_rgba(0,0,0,0.18)]"
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 z-10 flex size-8 items-center justify-center rounded-full bg-slate-100 text-base text-slate-500 transition hover:bg-slate-200"
        >
          ✕
        </button>
        <div className="mb-3 pr-10">
          <h3 className="text-base font-semibold text-slate-900">Разбивка операции</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            {sourceRow.direction === 'income' ? '↓ Доход' : '↑ Расход'} · {sourceRow.amount.toFixed(2)} ₽ · {sourceRow.description}
          </p>
        </div>
        <div className={phase === 'open' ? 'overflow-y-auto max-h-[calc(85vh-9rem)]' : ''}>
          {children}
        </div>
      </div>
    </>,
    document.body,
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Split editor — несколько частей, каждая со своим типом
// ───────────────────────────────────────────────────────────────────────────

function SplitEditor({
  parts,
  setParts,
  totalAmount,
  remaining,
  direction,
  categoryById,
  accountById,
  excludeAccountId,
}: {
  parts: Array<{
    operation_type: 'regular' | 'transfer' | 'refund' | 'debt';
    amount: string;
    category_id: number | null;
    target_account_id: number | null;
    debt_direction: 'borrowed' | 'lent' | 'repaid' | 'collected';
    debt_partner_id: number | null;
    description: string;
  }>;
  setParts: React.Dispatch<React.SetStateAction<typeof parts>>;
  totalAmount: number;
  remaining: number;
  direction: 'income' | 'expense';
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  excludeAccountId: number | null;
}) {
  // Debt parts need their own selector (debtor / creditor) — fetched once,
  // cached via React Query. Keeps the editor self-contained: no extra plumbing
  // through the AttentionCard parent.
  const debtPartnersQuery = useQuery({ queryKey: ['debt-partners'], queryFn: getDebtPartners });
  const debtPartners = debtPartnersQuery.data ?? [];
  const splitQueryClient = useQueryClient();
  // Which part is awaiting a newly-created partner / category so we can
  // auto-select it (mutation responses don't carry back the part index by
  // themselves).
  const [pendingCreateForPart, setPendingCreateForPart] = useState<number | null>(null);
  const [pendingCategoryForPart, setPendingCategoryForPart] = useState<number | null>(null);
  const createDebtPartnerMutation = useMutation({
    mutationFn: (name: string) =>
      createDebtPartner({ name, opening_balance_kind: 'receivable' }),
    onSuccess: (created) => {
      splitQueryClient.invalidateQueries({ queryKey: ['debt-partners'] });
      if (pendingCreateForPart != null) {
        setParts((prev) => prev.map((p, i) =>
          i === pendingCreateForPart ? { ...p, debt_partner_id: created.id } : p,
        ));
        setPendingCreateForPart(null);
      }
      toast.success(`Создан: ${created.name}`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать'),
  });
  const createCategoryMutation = useMutation({
    // Kind must match the part kind (income vs expense) — a refund part lives
    // under expense categories even though its direction is income; regular
    // parts follow the source operation's direction. Priority gets a sensible
    // default so the user doesn't have to leave the modal; they can refine
    // it later in the Категории section.
    mutationFn: ({ name, kind }: { name: string; kind: 'income' | 'expense' }) =>
      createCategory({
        name,
        kind,
        priority: kind === 'income' ? 'income_active' : 'expense_secondary',
      }),
    onSuccess: (created) => {
      splitQueryClient.invalidateQueries({ queryKey: ['categories'] });
      if (pendingCategoryForPart != null) {
        setParts((prev) => prev.map((p, i) =>
          i === pendingCategoryForPart ? { ...p, category_id: created.id } : p,
        ));
        setPendingCategoryForPart(null);
      }
      toast.success(`Категория создана: ${created.name}`);
    },
    onError: (err: Error) => toast.error(err.message || 'Не удалось создать категорию'),
  });
  const updatePart = (idx: number, patch: Partial<typeof parts[number]>) => {
    setParts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };
  const removePart = (idx: number) => {
    setParts((prev) => (prev.length <= 2 ? prev : prev.filter((_, i) => i !== idx)));
  };
  const addPart = () => {
    setParts((prev) => [...prev, {
      operation_type: 'regular',
      amount: '',
      category_id: null,
      target_account_id: null,
      debt_direction: 'borrowed',
      debt_partner_id: null,
      description: '',
    }]);
  };

  // Категории, доступные для каждой части — фильтруем по типу.
  const categoriesByKind = useMemo(() => {
    const out: Record<string, Category[]> = { income: [], expense: [] };
    for (const c of categoryById.values()) {
      if (c.kind === 'income') out.income.push(c);
      else out.expense.push(c);
    }
    out.income.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    out.expense.sort((a, b) => a.name.localeCompare(b.name, 'ru'));
    return out;
  }, [categoryById]);

  const accountsForTransfer = useMemo(
    () => Array.from(accountById.values()).filter((a) => a.id !== excludeAccountId),
    [accountById, excludeAccountId],
  );

  const remainingAbs = Math.abs(remaining);
  const remainingClass = remainingAbs < 0.01
    ? 'text-emerald-700'
    : remaining > 0 ? 'text-amber-800' : 'text-rose-700';
  const remainingLabel = remainingAbs < 0.01
    ? '✓ суммы совпали'
    : remaining > 0
      ? `осталось распределить ${remaining.toFixed(2)} ₽`
      : `превышение на ${Math.abs(remaining).toFixed(2)} ₽`;

  return (
    <div className="mt-2 ml-14 rounded-2xl border border-indigo-200 bg-indigo-50/40 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-indigo-900">
          Разбивка на {parts.length} {parts.length === 1 ? 'часть' : 'части'} · всего {totalAmount.toFixed(2)} ₽
        </p>
        <span className={`text-xs font-medium tabular-nums ${remainingClass}`}>{remainingLabel}</span>
      </div>

      {parts.map((part, idx) => {
        // Refund is semantically an expense compensator — its category should
        // match the original purchase being reversed, not an income category.
        // For all other types, follow the source operation's direction.
        const partKind: 'income' | 'expense' = part.operation_type === 'refund' ? 'expense' : direction;
        const partCategories = categoriesByKind[partKind] ?? [];
        // Debt parts don't take a category — they carry a debtor / creditor
        // instead. That's the whole reason we split the entity: a debt is a
        // relationship with a person, not a budget line.
        const needsCategory = part.operation_type === 'regular' || part.operation_type === 'refund';
        const needsTarget = part.operation_type === 'transfer';
        const needsDebtDir = part.operation_type === 'debt';
        const needsDebtPartner = part.operation_type === 'debt';
        return (
          <div key={idx} className="rounded-xl border border-indigo-100 bg-white p-2 flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-slate-500 w-6">#{idx + 1}</span>
            <CompactSelect
              value={part.operation_type}
              onChange={(v) => updatePart(idx, {
                operation_type: v as typeof part.operation_type,
                category_id: null,
                target_account_id: null,
              })}
              options={[
                { value: 'regular', label: 'Обычная' },
                { value: 'refund', label: 'Возврат' },
                { value: 'transfer', label: 'Перевод' },
                { value: 'debt', label: 'Долг' },
              ]}
              placeholder="Тип"
              widthClassName="w-32"
              ariaLabel="Тип операции части"
            />
            <input
              type="text"
              inputMode="decimal"
              value={part.amount}
              onChange={(e) => updatePart(idx, { amount: e.target.value })}
              placeholder="Сумма"
              className="h-8 w-24 rounded-lg border border-slate-200 bg-white px-2 text-xs tabular-nums text-right"
            />
            {needsCategory ? (
              <CompactSelect
                value={part.category_id != null ? String(part.category_id) : ''}
                onChange={(v) => updatePart(idx, { category_id: v ? Number(v) : null })}
                options={partCategories.map((c) => ({ value: String(c.id), label: c.name }))}
                placeholder="— категория —"
                widthClassName="w-44"
                ariaLabel="Категория части"
                createAction={{
                  visible: !createCategoryMutation.isPending,
                  label: '',
                  onClick: (name) => {
                    if (name) {
                      setPendingCategoryForPart(idx);
                      createCategoryMutation.mutate({ name, kind: partKind });
                    }
                  },
                }}
              />
            ) : null}
            {needsDebtPartner ? (
              <CompactSelect
                value={part.debt_partner_id != null ? String(part.debt_partner_id) : ''}
                onChange={(v) => updatePart(idx, { debt_partner_id: v ? Number(v) : null })}
                options={debtPartners.map((p) => ({ value: String(p.id), label: p.name }))}
                placeholder="— дебитор / кредитор —"
                widthClassName="w-52"
                ariaLabel="Дебитор или кредитор"
                createAction={{
                  visible: !createDebtPartnerMutation.isPending,
                  label: '',
                  onClick: (name) => {
                    if (name) {
                      setPendingCreateForPart(idx);
                      createDebtPartnerMutation.mutate(name);
                    }
                  },
                }}
              />
            ) : null}
            {needsDebtDir ? (
              <CompactSelect
                value={part.debt_direction}
                onChange={(v) => updatePart(idx, { debt_direction: v as typeof part.debt_direction })}
                options={[
                  { value: 'borrowed', label: 'Мне заняли / взял' },
                  { value: 'lent', label: 'Я одолжил' },
                  { value: 'repaid', label: 'Я вернул долг' },
                  { value: 'collected', label: 'Мне вернули' },
                ]}
                placeholder="Направление"
                widthClassName="w-44"
                ariaLabel="Направление долга"
              />
            ) : null}
            {needsTarget ? (
              <CompactSelect
                value={part.target_account_id != null ? String(part.target_account_id) : ''}
                onChange={(v) => updatePart(idx, { target_account_id: v ? Number(v) : null })}
                options={accountsForTransfer.map((a) => ({ value: String(a.id), label: a.name }))}
                placeholder="— счёт назначения —"
                widthClassName="w-48"
                ariaLabel="Счёт назначения"
              />
            ) : null}
            <input
              type="text"
              value={part.description}
              onChange={(e) => updatePart(idx, { description: e.target.value })}
              placeholder="Описание (опц.)"
              className="h-8 flex-1 min-w-[8rem] rounded-lg border border-slate-200 bg-white px-2 text-xs"
            />
            <button
              type="button"
              onClick={() => removePart(idx)}
              disabled={parts.length <= 2}
              className="h-8 px-2 text-xs text-rose-600 disabled:text-slate-300"
              title={parts.length <= 2 ? 'Нужно минимум 2 части' : 'Удалить часть'}
            >
              ✕
            </button>
          </div>
        );
      })}

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={addPart}
          className="text-xs font-medium text-indigo-700 hover:text-indigo-900"
        >
          + Добавить часть
        </button>
        <p className="text-[10px] text-slate-500">
          Применить можно когда сумма частей точно равна сумме операции.
        </p>
      </div>
    </div>
  );
}

// Memoized so a re-render of the parent (triggered by unrelated state like
// polling refetches or `scrollMargin` updates in the virtualizer) does not
// rerender every card in the list. Props are shallow-compared; `categoryById`
// and `accountById` are already stable `useMemo` Maps, and `onAfterAction` is
// a stable `useCallback` in the root panel.
const AttentionCard = memo(AttentionCardImpl);

// ───────────────────────────────────────────────────────────────────────────
// Bucket: Проверено — тайл, открывающийся в центр экрана
// ───────────────────────────────────────────────────────────────────────────

function ConfirmedBucket({
  rows,
  categoryById,
  accountById,
  sessionId,
  bulkClusters,
  onAfterAction,
}: {
  rows: FeedRow[];
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  sessionId: number;
  bulkClusters: BulkClustersResponse | undefined;
  onAfterAction: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (rows.length === 0) return null;

  const totalAmount = rows.reduce((s, r) => s + Math.abs(Number(r.amount) || 0), 0);

  const summaryNode = (
    <div className="flex w-full items-start gap-3">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
        <CheckCircle2 className="size-5" />
      </div>
      <div className="flex-1">
        <p className="text-base font-semibold text-slate-950">Проверено</p>
        <p className="text-sm text-slate-600">
          {rows.length} операц{rows.length === 1 ? 'ия' : rows.length < 5 ? 'ии' : 'ий'} на {formatMoney(totalAmount)} — готовы к импорту
        </p>
      </div>
    </div>
  );

  const collapsedNode = (
    <div className="flex w-full items-start gap-3">
      <div className="flex-1">{summaryNode}</div>
      <CollapsibleChevron open={expanded} className="size-4 shrink-0 self-center text-emerald-500" />
    </div>
  );

  const expandedNode = (
    <div className="flex flex-col gap-3">
      <div className="pr-10">{summaryNode}</div>
      <div
        className="overflow-y-auto rounded-2xl bg-white p-2 ring-1 ring-emerald-100"
        style={{ maxHeight: 'min(58vh, 600px)' }}
      >
        <div className="flex flex-col gap-2">
          {rows.map((feedRow) => (
            <AttentionCard
              key={feedRow.row.id}
              feedRow={feedRow}
              categoryById={categoryById}
              accountById={accountById}
              sessionId={sessionId}
              bulkClusters={bulkClusters}
              onAfterAction={onAfterAction}
            />
          ))}
        </div>
      </div>
      <p className="text-xs text-slate-400">
        Эти строки уже помечены как «готовые»: категория проставлена, ошибок нет. Можно жать «Импортировать готовые» в шапке, чтобы создать транзакции разом, или пересмотреть отдельные строки здесь.
      </p>
    </div>
  );

  return (
    <div className="rounded-2xl border-2 border-emerald-200 bg-emerald-50 p-4">
      <ExpandableCard
        isOpen={expanded}
        onToggle={() => setExpanded((v) => !v)}
        expandedWidth="860px"
        collapsed={collapsedNode}
        expanded={expandedNode}
      />
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Bucket 3: Исключённые — коллапсируемый список с кнопкой «Вернуть»
// ───────────────────────────────────────────────────────────────────────────

function ExcludedBucket({
  rows,
  onAfterAction,
}: {
  rows: FeedRow[];
  onAfterAction: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  if (rows.length === 0) return null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <button
        type="button"
        className="flex w-full items-center justify-between text-left"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span className="text-sm font-semibold text-slate-600">
          Исключено из импорта ({rows.length})
        </span>
        <CollapsibleChevron open={expanded} className="size-4 text-slate-400" />
      </button>

      <Collapsible open={expanded}>
        <div className="mt-3 space-y-1">
          {rows.map((feedRow) => (
            <ExcludedRow
              key={feedRow.row.id}
              feedRow={feedRow}
              onAfterAction={onAfterAction}
            />
          ))}
        </div>
      </Collapsible>
    </div>
  );
}

function ExcludedRow({ feedRow, onAfterAction }: { feedRow: FeedRow; onAfterAction: () => void }) {
  const { row, date, description, amount, direction } = feedRow;

  const unexcludeMutation = useMutation({
    mutationFn: () => unexcludeImportRow(row.id),
    onSuccess: () => { toast.success(`Возвращено #${row.row_index}`); onAfterAction(); },
    onError: (error: Error) => toast.error(`Ошибка: ${error.message}`),
  });

  const shortDesc = description.length > 70 ? description.slice(0, 70).trim() + '…' : description;

  return (
    <div className="flex items-center gap-3 rounded-xl bg-white px-3 py-2 text-sm text-slate-400">
      <span className="w-10 shrink-0 tabular-nums">{formatDateShort(date)}</span>
      <span className="min-w-0 flex-1 truncate line-through" title={description}>{shortDesc}</span>
      <span className={`shrink-0 tabular-nums text-xs ${direction === 'income' ? 'text-emerald-500' : ''}`}>
        {formatSignedAmount(amount, direction)}
      </span>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => unexcludeMutation.mutate()}
        disabled={unexcludeMutation.isPending}
      >
        Вернуть
      </Button>
    </div>
  );
}

/**
 * Filterable search-select for row-level pickers. Wraps SearchSelect with a
 * local query state so call sites don't need to plumb through query+setQuery.
 *
 * Dropdown opens as an animated portal-overlay below the input (anchored), so
 * it doesn't push neighbouring items in flex-wrap rows.
 */
function CompactSelect({
  value,
  onChange,
  options,
  placeholder,
  widthClassName,
  tone = 'slate',
  ariaLabel,
  createAction,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
  placeholder: string;
  widthClassName: string;
  tone?: 'slate' | 'indigo';
  ariaLabel: string;
  // Optional "create new" button that shows when the query doesn't match any
  // option. onClick receives the current trimmed query so callers can create
  // a new entity (e.g. a DebtPartner) inline. The same callback is responsible
  // for eventually flipping `value` to the new id — typically via onChange
  // from within the create mutation's onSuccess handler.
  createAction?: {
    visible: boolean;
    label: string;
    onClick: (query: string) => void;
  };
}) {
  const reactId = useId();
  const selected = options.find((o) => o.value === value) ?? null;
  const [query, setQuery] = useState<string>(selected?.label ?? '');
  useEffect(() => {
    setQuery(selected?.label ?? '');
  }, [selected]);
  const items: SearchSelectItem[] = options.map((o) => ({ value: o.value, label: o.label }));
  const toneClass = tone === 'indigo'
    ? 'bg-indigo-50 text-indigo-900 border-indigo-200 focus:border-indigo-400'
    : 'bg-white text-slate-900 border-slate-200 focus:border-slate-400';
  const trimmed = query.trim();
  return (
    <SearchSelect
      id={reactId}
      label={ariaLabel}
      hideLabel
      placeholder={placeholder}
      widthClassName={widthClassName}
      query={query}
      setQuery={setQuery}
      items={items}
      selectedValue={value}
      onSelect={(item) => {
        onChange(item.value);
        setQuery(item.label);
      }}
      showAllOnFocus
      inputSize="sm"
      inputClassName={`text-xs font-medium shadow-sm ${toneClass}`}
      createAction={createAction ? {
        // Show only when the query is non-empty AND doesn't exactly match
        // any existing option. Matches the "find-or-create" pattern from
        // the cluster-card counterparty selector.
        visible:
          createAction.visible
          && trimmed.length > 0
          && !options.some((o) => o.label.trim().toLowerCase() === trimmed.toLowerCase()),
        label: createAction.label || (trimmed ? `+ Создать «${trimmed}»` : ''),
        onClick: () => createAction.onClick(trimmed),
      } : undefined}
    />
  );
}

function MainOpPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const options = [
    { value: 'regular', label: 'Обычная' },
    { value: 'transfer', label: 'Перевод' },
    { value: 'debt', label: 'Долг' },
    { value: 'refund', label: 'Возврат' },
    { value: 'investment', label: 'Инвестиция' },
    { value: 'credit_operation', label: 'Кредитная операция' },
  ];
  return (
    <CompactSelect
      value={value}
      onChange={onChange}
      options={options}
      placeholder="Тип"
      widthClassName="w-36"
      ariaLabel="Тип операции"
    />
  );
}

function SubPicker({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: Array<{ value: string; label: string }>;
}) {
  return (
    <CompactSelect
      value={value}
      onChange={onChange}
      options={options}
      placeholder="Уточнить"
      widthClassName="w-44"
      tone="indigo"
      ariaLabel="Уточнение типа"
    />
  );
}

/**
 * Category picker with type-ahead filtering. Uses the shared SearchSelect so
 * the animation and keyboard behavior match every other picker on the import
 * page. "+ новая категория" opens the standard CategoryDialog when the typed
 * text doesn't match an existing category.
 */
function CategoryPicker({
  value,
  onChange,
  categories,
  kindHint,
}: {
  value: number | null;
  onChange: (id: number | null) => void;
  categories: Category[];
  kindHint: 'income' | 'expense';
}) {
  const queryClient = useQueryClient();
  const reactId = useId();
  const selected = value != null ? categories.find((c) => c.id === value) ?? null : null;
  const [query, setQuery] = useState<string>(selected?.name ?? '');
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    setQuery(selected?.name ?? '');
  }, [selected]);

  const items: SearchSelectItem[] = categories.map((c) => ({ value: String(c.id), label: c.name }));
  const trimmed = query.trim();
  const exactMatch = categories.some((c) => c.name.toLowerCase() === trimmed.toLowerCase());
  const canCreate = trimmed.length > 0 && !exactMatch;

  const createMutation = useMutation({
    mutationFn: (payload: CreateCategoryPayload) => createCategory(payload),
    onSuccess: (created) => {
      toast.success(`Категория «${created.name}» создана`);
      queryClient.invalidateQueries({ queryKey: ['categories'] });
      setDialogOpen(false);
      onChange(created.id);
      setQuery(created.name);
    },
    onError: (error: Error) => {
      toast.error(`Не удалось создать: ${error.message}`);
    },
  });

  // Auto-select on blur: if the user typed a category name and tabbed/clicked
  // away without clicking the dropdown item, we resolve the match so the
  // button doesn't stay disabled on exact text matches.
  const handleBlur = () => {
    if (value != null) return; // already selected
    const q = query.trim().toLowerCase();
    if (!q) return;
    const match = categories.find((c) => c.name.toLowerCase() === q);
    if (match) {
      onChange(match.id);
      setQuery(match.name);
    }
  };

  return (
    <>
      <SearchSelect
        id={reactId}
        label="Категория"
        hideLabel
        placeholder="— выбрать категорию —"
        widthClassName="w-48"
        query={query}
        setQuery={setQuery}
        items={items}
        selectedValue={value != null ? String(value) : null}
        onSelect={(item) => {
          onChange(item.value ? Number(item.value) : null);
          setQuery(item.label);
        }}
        onBlur={handleBlur}
        showAllOnFocus
        inputSize="sm"
        inputClassName="text-xs font-medium shadow-sm"
        createAction={{
          visible: canCreate,
          label: trimmed ? `+ Новая категория «${trimmed}»` : '+ Новая категория',
          onClick: () => setDialogOpen(true),
        }}
      />
      <CategoryDialog
        open={dialogOpen}
        mode="create"
        initialValues={{ kind: kindHint, name: trimmed || undefined }}
        isSubmitting={createMutation.isPending}
        onClose={() => setDialogOpen(false)}
        onSubmit={(values) => createMutation.mutate(values)}
      />
    </>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Small pieces
// ───────────────────────────────────────────────────────────────────────────

function ZoneBadge({ zone }: { zone: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    green: { label: 'Готово', cls: 'bg-emerald-100 text-emerald-800' },
    yellow: { label: 'Проверь', cls: 'bg-amber-100 text-amber-800' },
    red: { label: 'Нужен ответ', cls: 'bg-rose-100 text-rose-800' },
  };
  const entry = map[zone] ?? map.yellow;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${entry.cls}`}>
      {entry.label}
    </span>
  );
}

function GlobalPatternHint({ cluster }: { cluster: ModerationClusterEntry | null }) {
  const n = cluster?.global_pattern_user_count;
  const cat = cluster?.global_pattern_category_name;
  if (!n || n <= 0 || !cat) return null;
  return (
    <p className="mt-1.5 text-xs text-violet-700">
      🧠 {n} {n === 1 ? 'пользователь' : n < 5 ? 'пользователя' : 'пользователей'} этого банка
      {' '}относят такие операции в категорию <strong>«{cat}»</strong>
    </p>
  );
}

function BankMechanicsHint({ cluster }: { cluster: ModerationClusterEntry | null }) {
  if (!cluster?.bank_mechanics_label && !cluster?.bank_mechanics_cross_session_warning) return null;
  return (
    <div className="mt-1.5 space-y-1">
      {cluster?.bank_mechanics_label ? (
        <p className="text-xs text-indigo-700">
          🏦 {cluster.bank_mechanics_label}
        </p>
      ) : null}
      {cluster?.bank_mechanics_cross_session_warning ? (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
          ⚠️ {cluster.bank_mechanics_cross_session_warning}
        </p>
      ) : null}
    </div>
  );
}

function AccountContextHint({ cluster }: { cluster: ModerationClusterEntry | null }) {
  // Don't duplicate — if bank mechanics already gave a label, skip generic account hint.
  if (cluster?.bank_mechanics_label) return null;
  if (!cluster?.account_context_label) return null;
  return (
    <p className="mt-1.5 text-xs text-indigo-700">
      🏦 {cluster.account_context_label}
    </p>
  );
}

function RefundPairHint({ match }: { match: RefundMatchMeta | null }) {
  if (!match) return null;
  const dateStr = match.partner_date ? String(match.partner_date).slice(0, 10) : '';
  const amount = match.amount ?? '';
  const desc = (match.partner_description ?? '').trim();
  const shortDesc = desc.length > 60 ? desc.slice(0, 60).trim() + '…' : desc;
  const verb = match.side === 'income'
    ? 'Возврат покупки'
    : 'Найдена парная отмена';
  const confidencePct = Math.round((match.confidence ?? 0) * 100);
  return (
    <p className="mt-1.5 rounded-xl border border-emerald-300 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900">
      ↩ {verb}{dateStr ? ` от ${dateStr}` : ''}{amount ? ` на ${amount} ₽` : ''}
      {shortDesc ? ` — «${shortDesc}»` : ''}
      <span className="ml-2 text-emerald-700/70">уверенность {confidencePct}%</span>
    </p>
  );
}

function TrustSignal({ cluster }: { cluster: ModerationClusterEntry | null }) {
  if (!cluster || !cluster.rule_source || cluster.rule_source === 'none') return null;

  const idMatch = cluster.identifier_match;
  const confirms = cluster.rule_confirms ?? 0;
  const rejections = cluster.rule_rejections ?? 0;
  const idValue = cluster.identifier_value;

  if (idMatch === 'matched' && idValue) {
    return (
      <p className="mt-1.5 text-xs text-emerald-700">
        ✓ Тот же идентификатор <strong>{idValue}</strong>, что и {confirms} раз
        {rejections > 0 ? ` (и ${rejections} отказов)` : ''}
      </p>
    );
  }
  if (idMatch === 'unmatched') {
    return (
      <p className="mt-1.5 text-xs text-amber-800">
        ⚠ {idValue ? (
          <>Новый идентификатор <strong>{idValue}</strong></>
        ) : (
          <>Идентификатор, которого AI ещё не видел</>
        )}
        {' '}— похоже по шаблону, но ты такое ещё не размечал
      </p>
    );
  }
  if (confirms > 0) {
    const ratio = confirms + rejections > 0 ? confirms / (confirms + rejections) : 1;
    const tone = ratio > 0.9 ? 'text-emerald-700' : 'text-slate-600';
    return (
      <p className={`mt-1.5 text-xs ${tone}`}>
        ✓ Правило срабатывало {confirms} раз
        {rejections > 0 ? `, отклонено ${rejections}` : ''}
      </p>
    );
  }
  return null;
}

function formatDateShort(raw: string): string {
  if (!raw) return '—';
  const s = String(raw).slice(0, 10);  // YYYY-MM-DD
  const parts = s.split('-');
  if (parts.length !== 3) return s;
  return `${parts[2]}.${parts[1]}`;
}

function formatSignedAmount(raw: string, direction: string): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  const abs = Math.abs(n);
  const sign = direction === 'income' ? '+' : '−';
  return `${sign}${abs.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 2 })} ₽`;
}

function formatMoney(n: number): string {
  return `${n.toLocaleString('ru-RU', { minimumFractionDigits: 0, maximumFractionDigits: 0 })} ₽`;
}
