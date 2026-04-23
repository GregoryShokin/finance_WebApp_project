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

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Loader2, Plus, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { CategoryDialog } from '@/components/categories/category-dialog';
import {
  excludeImportRow,
  getImportPreview,
  getModerationStatus,
  parkImportRow,
  startModeration,
  unexcludeImportRow,
  updateImportRow,
} from '@/lib/api/imports';
import { getAccounts } from '@/lib/api/accounts';
import { createCategory, getCategories } from '@/lib/api/categories';
import type { Account } from '@/types/account';
import type {
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

  const previewQuery = useQuery({
    queryKey: ['imports', sessionId, 'preview'],
    queryFn: () => getImportPreview(sessionId),
  });

  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: () => getCategories(),
  });

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: () => getAccounts(),
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
        };
      })
      .sort((a, b) => b.date.localeCompare(a.date));
  }, [previewQuery.data, statusQuery.data]);

  const excludedFeed = feed.filter((f) => f.isExcluded);
  const activeFeed = feed.filter((f) => !f.isExcluded);

  const transferFeed = activeFeed.filter(
    (f) => f.operationType === 'transfer' || f.isDuplicateSide,
  );
  const remainingFeed = activeFeed.filter(
    (f) => f.operationType !== 'transfer' && !f.isDuplicateSide,
  );
  const autoTrustFeed = remainingFeed.filter((f) => f.cluster?.auto_trust === true);
  const attentionFeed = remainingFeed.filter((f) => f.cluster?.auto_trust !== true);

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

  const status = statusQuery.data;
  const notStarted = !status || status.status === 'not_started';
  const isRunning = status?.status === 'running' || status?.status === 'pending';
  const isReady = status?.status === 'ready';
  const isFailed = status?.status === 'failed';
  const isSkipped = status?.status === 'skipped';

  const afterMutation = () => {
    queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'moderation-status'] });
    queryClient.invalidateQueries({ queryKey: ['imports', sessionId, 'preview'] });
    onClustersChanged?.();
  };

  const feedReady = status && (isReady || status.processed_clusters > 0) && feed.length > 0;

  return (
    <Card className="rounded-3xl bg-white p-5 shadow-soft lg:p-6">
      <Header
        status={status}
        isRunning={isRunning}
        onStart={() => startMutation.mutate()}
        startPending={startMutation.isPending}
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
            autoRows={autoTrustFeed.length + transferFeed.length}
            attentionRows={attentionFeed.length}
          />

          <TransfersBucket rows={transferFeed} accountById={accountById} />

          <AutoTrustBucket rows={autoTrustFeed} categoryById={categoryById} />

          <AttentionBucket
            rows={attentionFeed}
            categoryById={categoryById}
            accountById={accountById}
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
}: {
  status?: ModerationStatusResponse;
  isRunning: boolean;
  onStart: () => void;
  startPending: boolean;
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
      {!isRunning && (
        <Button variant="primary" onClick={onStart} disabled={startPending}>
          <Sparkles className="size-4" />
          {status && !['not_started', 'pending'].includes(status.status)
            ? 'Перезапустить'
            : 'Запустить модератор'}
        </Button>
      )}
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

  return (
    <div className="rounded-2xl border-2 border-indigo-200 bg-indigo-50 p-4">
      <button
        type="button"
        className="flex w-full items-start gap-3 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
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
        <span className="shrink-0 text-xs text-indigo-500 self-center">{expanded ? '▲ Скрыть' : '▼ Показать'}</span>
      </button>

      {expanded && (
        <div className="mt-3 rounded-2xl bg-white p-3 ring-1 ring-indigo-200">
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
          <p className="mt-2 text-xs text-slate-400">
            Дубли не импортируются повторно. Переводы создадутся как парные транзакции.
          </p>
        </div>
      )}
    </div>
  );
}

function TransferRow({ feedRow, accountById }: { feedRow: FeedRow; accountById: Map<number, Account> }) {
  const { row, date, description, amount, direction, targetAccountId, isDuplicateSide } = feedRow;

  const shortDesc = description.length > 55 ? description.slice(0, 55).trim() + '…' : description;

  const sourceId = (row.normalized_data as Record<string, any>)?.account_id
    ? Number((row.normalized_data as Record<string, any>).account_id)
    : null;
  const sourceName = sourceId ? (accountById.get(sourceId)?.name ?? `#${sourceId}`) : null;
  const targetName = targetAccountId
    ? (accountById.get(targetAccountId)?.name ?? `#${targetAccountId}`)
    : null;

  const linkLabel = isDuplicateSide
    ? 'Дубль · другая сессия'
    : sourceName && targetName
      ? `${sourceName} → ${targetName}`
      : sourceName && targetAccountId
        ? `${sourceName} → счёт #${targetAccountId}`
        : targetName
          ? `→ ${targetName}`
          : 'перевод между своими';
  const linkClass = isDuplicateSide ? 'text-slate-400' : 'text-indigo-700 font-medium';

  return (
    <tr className={isDuplicateSide ? 'text-slate-400 italic' : 'text-slate-800'}>
      <td className="px-2 py-2 tabular-nums">{formatDateShort(date)}</td>
      <td className="px-2 py-2 truncate" title={description}>{shortDesc}</td>
      <td className={`px-2 py-2 text-xs ${linkClass}`}>{linkLabel}</td>
      <td className={`px-2 py-2 text-right tabular-nums ${direction === 'income' ? 'text-emerald-600' : 'text-slate-900'} ${isDuplicateSide ? 'line-through' : ''}`}>
        {formatSignedAmount(amount, direction)}
      </td>
    </tr>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Bucket 1: Готово к импорту — таблица отдельных транзакций
// ───────────────────────────────────────────────────────────────────────────

function AutoTrustBucket({
  rows,
  categoryById,
}: {
  rows: FeedRow[];
  categoryById: Map<number, Category>;
}) {
  const [expanded, setExpanded] = useState(false);

  if (rows.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
        🌱 Пока нет строк с полным доверием. Подтверди категории в «Требуют внимания» — в следующий раз их станет больше.
      </div>
    );
  }
  const totalAmount = rows.reduce((s, r) => s + Math.abs(Number(r.amount) || 0), 0);

  return (
    <div className="rounded-2xl border-2 border-emerald-200 bg-emerald-50 p-4">
      <button
        type="button"
        className="flex w-full items-start gap-3 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-emerald-500">
          <CheckCircle2 className="size-5 text-white" />
        </div>
        <div className="flex-1">
          <p className="text-base font-semibold text-slate-950">Готово к импорту</p>
          <p className="text-sm text-slate-600">
            {rows.length} транзакций · {formatMoney(totalAmount)} · уверенность ≥ 99%
          </p>
        </div>
        <span className="shrink-0 text-xs text-emerald-600 self-center">{expanded ? '▲ Скрыть' : '▼ Показать'}</span>
      </button>

      {expanded && (
        <div className="mt-3 rounded-2xl bg-white p-3 ring-1 ring-emerald-200">
          <table className="w-full text-sm table-fixed">
            <thead>
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                <th className="px-2 py-2 w-14">Дата</th>
                <th className="px-2 py-2">Описание</th>
                <th className="px-2 py-2 w-36">Категория</th>
                <th className="px-2 py-2 text-right w-28">Сумма</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((feedRow) => (
                <AutoTrustTableRow
                  key={feedRow.row.id}
                  feedRow={feedRow}
                  categoryById={categoryById}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AutoTrustTableRow({
  feedRow,
  categoryById,
}: {
  feedRow: FeedRow;
  categoryById: Map<number, Category>;
}) {
  const { cluster, date, description, amount, direction } = feedRow;
  const catId = cluster?.candidate_category_id ?? cluster?.hypothesis?.predicted_category_id ?? null;
  const catName = catId ? categoryById.get(catId)?.name ?? '—' : '—';
  const signal = cluster?.identifier_value
    ? `Тот же ${cluster.identifier_value}, ${cluster.rule_confirms ?? 0}×`
    : `Правило, ${cluster?.rule_confirms ?? 0} подтв.`;

  return (
    <tr className="text-slate-800">
      <td className="px-2 py-2 tabular-nums text-slate-500">{formatDateShort(date)}</td>
      <td className="px-2 py-2 truncate" title={`${description}\n${signal}`}>{description}</td>
      <td className="px-2 py-2 truncate">
        <span className="inline-flex max-w-full truncate rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
          {catName}
        </span>
      </td>
      <td className={`px-2 py-2 text-right tabular-nums ${direction === 'income' ? 'text-emerald-600' : 'text-slate-900'}`}>
        {formatSignedAmount(amount, direction)}
      </td>
    </tr>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Bucket 2: Требуют внимания — лента карточек-транзакций
// ───────────────────────────────────────────────────────────────────────────

function AttentionBucket({
  rows,
  categoryById,
  accountById,
  onAfterAction,
}: {
  rows: FeedRow[];
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  onAfterAction: () => void;
}) {
  if (rows.length === 0) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
        🎉 Все строки в «Готово к импорту». Ничего разбирать не надо.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-base font-semibold text-slate-900">
          Требуют твоего внимания ({rows.length} транзакций)
        </p>
        <p className="text-xs text-slate-500">Выбери категорию, подтверди или отложи</p>
      </div>
      <div className="space-y-2">
        {rows.map((feedRow) => (
          <AttentionCard
            key={feedRow.row.id}
            feedRow={feedRow}
            categoryById={categoryById}
            accountById={accountById}
            onAfterAction={onAfterAction}
          />
        ))}
      </div>
    </div>
  );
}

function AttentionCard({
  feedRow,
  categoryById,
  accountById,
  onAfterAction,
}: {
  feedRow: FeedRow;
  categoryById: Map<number, Category>;
  accountById: Map<number, Account>;
  onAfterAction: () => void;
}) {
  const { row, cluster, date, description, amount, direction, refundMatch } = feedRow;
  const zone = cluster?.trust_zone ?? 'yellow';
  const zoneClass: Record<string, string> = {
    yellow: 'border-slate-200 bg-white',
    red: 'border-slate-200 bg-white',
    green: 'border-slate-200 bg-white',
  };
  const suggestedCatId =
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

  // ── Разбивка на части (split) ──────────────────────────────────────────────
  // Каждая часть — мини-транзакция со своим типом, суммой и нужными полями.
  // Сумма частей должна точно совпадать с суммой исходной строки.
  type SplitPart = {
    operation_type: 'regular' | 'transfer' | 'refund' | 'debt';
    amount: string;
    category_id: number | null;
    target_account_id: number | null;
    debt_direction: 'borrowed' | 'lent' | 'repaid' | 'collected';
    description: string;
  };
  const emptyPart = (): SplitPart => ({
    operation_type: 'regular',
    amount: '',
    category_id: null,
    target_account_id: null,
    debt_direction: 'borrowed',
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
    if (p.operation_type === 'debt' && !p.category_id) return false;
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

  // Нужна ли выборка категории?
  const needsCategory = mainOp === 'regular' || mainOp === 'debt' || mainOp === 'refund';
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

  // У строки есть «черновик» разбивки, если в state хоть одна часть имеет
  // непустую сумму. Это не зависит от того, открыта ли модалка.
  const hasSplitDraft = splitParts.some((p) => p.amount && parseFloat(p.amount.replace(',', '.')) > 0);

  // Проверяем готовность «Применить»:
  const canApply = (() => {
    // Split-режим: если разбивка введена — обязательно валидной должна быть.
    if (hasSplitDraft) return splitValid;
    if (mainOp === 'regular' || mainOp === 'refund') return Boolean(pickedCatId);
    if (mainOp === 'debt') return Boolean(pickedCatId);
    if (mainOp === 'credit_operation' && creditKind === 'payment') {
      const p = parseFloat(creditPrincipal.replace(',', '.'));
      const i = parseFloat(creditInterest.replace(',', '.'));
      return Number.isFinite(p) && p >= 0 && Number.isFinite(i) && i >= 0;
    }
    // transfer, investment, credit_disbursement, credit_early_repayment — применяем всегда
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
            category_id: p.category_id,
            target_account_id: p.target_account_id,
            debt_direction: p.operation_type === 'debt' ? p.debt_direction : null,
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
      if (mainOp === 'debt') payload.debt_direction = debtDir;
      if (mainOp === 'credit_operation' && creditKind === 'payment') {
        payload.credit_principal_amount = parseFloat(creditPrincipal.replace(',', '.')) || 0;
        payload.credit_interest_amount = parseFloat(creditInterest.replace(',', '.')) || 0;
      }
      await updateImportRow(row.id, payload);
    },
    onSuccess: () => {
      toast.success(`Применено к строке #${row.row_index}`);
      onAfterAction();
    },
    onError: (error: Error) => toast.error(`Не удалось применить: ${error.message}`),
  });

  // Shorten pathologically long parser-mangled descriptions — keep ≤ 100 chars
  // to fight PDF-extract noise like "Договора Оплата товаров и услуг...11 361,00 ₽ 11 361,00 ₽..."
  const displayDescription =
    description.length > 100 ? description.slice(0, 100).trim() + '…' : description;

  return (
    <div className={`overflow-hidden rounded-2xl border p-3 ${zoneClass[zone] ?? zoneClass.yellow}`}>
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
        ) : mainOp !== 'credit_operation' || creditKind === 'payment' ? null : (
          <span className="text-xs text-slate-500">
            Счёт назначь в секции «Импорт перед коммитом» ниже
          </span>
        )}

        <div className="ml-auto flex items-center gap-1">
          <SplitButton
            active={splitOpen || splitParts.some((p) => p.amount)}
            onClick={() => setSplitOpen(true)}
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
        const partKind: 'income' | 'expense' = part.operation_type === 'refund' ? 'income' : direction;
        const partCategories = categoriesByKind[partKind] ?? [];
        const needsCategory = part.operation_type === 'regular' || part.operation_type === 'refund' || part.operation_type === 'debt';
        const needsTarget = part.operation_type === 'transfer';
        const needsDebtDir = part.operation_type === 'debt';
        return (
          <div key={idx} className="rounded-xl border border-indigo-100 bg-white p-2 flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-slate-500 w-6">#{idx + 1}</span>
            <select
              value={part.operation_type}
              onChange={(e) => updatePart(idx, {
                operation_type: e.target.value as typeof part.operation_type,
                category_id: null,
                target_account_id: null,
              })}
              className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs"
            >
              <option value="regular">Обычная</option>
              <option value="refund">Возврат</option>
              <option value="transfer">Перевод</option>
              <option value="debt">Долг</option>
            </select>
            <input
              type="text"
              inputMode="decimal"
              value={part.amount}
              onChange={(e) => updatePart(idx, { amount: e.target.value })}
              placeholder="Сумма"
              className="h-8 w-24 rounded-lg border border-slate-200 bg-white px-2 text-xs tabular-nums text-right"
            />
            {needsCategory ? (
              <select
                value={part.category_id ?? ''}
                onChange={(e) => updatePart(idx, { category_id: e.target.value ? Number(e.target.value) : null })}
                className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs min-w-[10rem]"
              >
                <option value="">— категория —</option>
                {partCategories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            ) : null}
            {needsDebtDir ? (
              <select
                value={part.debt_direction}
                onChange={(e) => updatePart(idx, { debt_direction: e.target.value as typeof part.debt_direction })}
                className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs"
              >
                <option value="borrowed">Мне заняли / взял</option>
                <option value="lent">Я одолжил</option>
                <option value="repaid">Я вернул долг</option>
                <option value="collected">Мне вернули</option>
              </select>
            ) : null}
            {needsTarget ? (
              <select
                value={part.target_account_id ?? ''}
                onChange={(e) => updatePart(idx, { target_account_id: e.target.value ? Number(e.target.value) : null })}
                className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs min-w-[10rem]"
              >
                <option value="">— счёт назначения —</option>
                {accountsForTransfer.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
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
      >
        <span className="text-sm font-semibold text-slate-600">
          Исключено из импорта ({rows.length})
        </span>
        <span className="text-xs text-slate-400">{expanded ? '▲ Скрыть' : '▼ Показать'}</span>
      </button>

      {expanded && (
        <div className="mt-3 space-y-1">
          {rows.map((feedRow) => (
            <ExcludedRow
              key={feedRow.row.id}
              feedRow={feedRow}
              onAfterAction={onAfterAction}
            />
          ))}
        </div>
      )}
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
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-lg border border-slate-200 bg-white px-2 text-xs font-medium text-slate-900 shadow-sm outline-none focus:border-slate-400"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
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
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-lg border border-indigo-200 bg-indigo-50 px-2 text-xs font-medium text-indigo-900 shadow-sm outline-none focus:border-indigo-400"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

/**
 * Inline autocomplete picker: type to filter by name. Shows "+ новая категория"
 * button at the end of the list that opens the standard CategoryDialog.
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
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selected = value ? categories.find((c) => c.id === value) ?? null : null;
  const displayValue = open ? query : selected?.name ?? '';

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return categories.slice(0, 10);
    return categories.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 10);
  }, [categories, query]);

  // Position the floating dropdown anchored to the input. Runs in layout
  // effect so we pick up the right coordinates before paint.
  useLayoutEffect(() => {
    if (!open || !inputRef.current) return;
    const update = () => {
      if (!inputRef.current) return;
      const r = inputRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 4, left: r.left, width: Math.max(240, r.width) });
    };
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
    };
  }, [open]);

  // Close on outside click — looks at both input and dropdown nodes (they
  // live in different DOM trees because of the portal).
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      const t = e.target as Node;
      if (inputRef.current && inputRef.current.contains(t)) return;
      if (dropdownRef.current && dropdownRef.current.contains(t)) return;
      setOpen(false);
      setQuery('');
    }
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const createMutation = useMutation({
    mutationFn: (payload: CreateCategoryPayload) => createCategory(payload),
    onSuccess: (created) => {
      toast.success(`Категория «${created.name}» создана`);
      queryClient.invalidateQueries({ queryKey: ['categories'] });
      setDialogOpen(false);
      onChange(created.id);
    },
    onError: (error: Error) => {
      toast.error(`Не удалось создать: ${error.message}`);
    },
  });

  const dropdown =
    open && pos && typeof document !== 'undefined'
      ? createPortal(
          <div
            ref={dropdownRef}
            className="z-[100] rounded-xl border border-slate-200 bg-white shadow-xl"
            style={{ position: 'fixed', top: pos.top, left: pos.left, width: pos.width }}
          >
            <ul className="max-h-56 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <li className="px-3 py-2 text-xs text-slate-400">Ничего не найдено</li>
              ) : (
                filtered.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        onChange(c.id);
                        setOpen(false);
                        setQuery('');
                      }}
                      className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-50 ${
                        c.id === value ? 'bg-slate-100 font-medium' : ''
                      }`}
                    >
                      <span className="truncate">{c.name}</span>
                      {c.id === value ? <span className="text-xs text-slate-400">✓</span> : null}
                    </button>
                  </li>
                ))
              )}
            </ul>
            <div className="border-t border-slate-100 p-1">
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setOpen(false);
                  setDialogOpen(true);
                }}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs font-medium text-indigo-600 hover:bg-indigo-50"
              >
                <Plus className="size-3.5" />
                Новая категория
              </button>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <input
        ref={inputRef}
        type="text"
        value={displayValue}
        placeholder="— выбрать категорию —"
        onFocus={() => {
          setOpen(true);
          setQuery('');
        }}
        onChange={(e) => {
          setOpen(true);
          setQuery(e.target.value);
        }}
        className="h-8 w-44 rounded-lg border border-slate-200 bg-white px-2 text-xs font-medium text-slate-900 shadow-sm outline-none focus:border-slate-400"
      />
      {dropdown}
      <CategoryDialog
        open={dialogOpen}
        mode="create"
        initialValues={{ kind: kindHint, name: query || undefined }}
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
