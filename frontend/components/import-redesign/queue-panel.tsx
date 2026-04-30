'use client';

/**
 * Modal queue list — opens above the queue-pill in the action bar.
 * Each row: status dot + bank icon + filename + account select + period +
 * action button (Начать / Продолжить / Импортировать / Открыть). Rows are
 * collapsible; expanded view shows a counterparty preview.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import { ArrowRight, Check, ChevronDown, ChevronRight, FileText, Loader2, Plus, Trash2, Wallet, X } from 'lucide-react';
import { toast } from 'sonner';

import { BankIcon } from '@/components/ui/bank-icon';
import { Chip } from '@/components/ui/status-chip';
import { AccountDialog } from '@/components/accounts/account-dialog';
import {
  assignSessionAccount,
  deleteImportSession,
  getBulkClusters,
  getImportPreview,
  getImportSession,
} from '@/lib/api/imports';
import { createAccount, getAccounts } from '@/lib/api/accounts';
import { fmtPeriod } from './format';
import type {
  Account, CreateAccountPayload,
} from '@/types/account';
import type { ImportSessionListItem, BulkClustersResponse, ImportPreviewResponse } from '@/types/import';

type QueueStatus =
  | 'parsing'      // auto_preview running
  | 'ready'        // uploaded, awaiting moderation kick-off
  | 'progress'     // partial moderation in progress
  | 'done_local'   // ready to commit (all rows decided)
  | 'error';       // auto_preview failed

function classifySession(s: ImportSessionListItem): QueueStatus {
  if (s.auto_preview_status === 'pending' || s.auto_preview_status === 'running') return 'parsing';
  if (s.auto_preview_status === 'failed' || s.status === 'failed') return 'error';
  if (s.status === 'committed') return 'done_local'; // edge case: shouldn't appear
  if (s.row_count > 0 && s.ready_count === s.row_count) return 'done_local';
  if (s.ready_count > 0) return 'progress';
  return 'ready';
}

const STATUS_LABEL: Record<QueueStatus, string> = {
  parsing: 'Распознаём…',
  ready: 'Готова к разбору',
  progress: 'В процессе',
  done_local: 'Готова к импорту',
  error: 'Ошибка формата',
};
const STATUS_DOT: Record<QueueStatus, string> = {
  parsing: 'bg-accent-violet',
  ready: 'bg-ink-3',
  progress: 'bg-accent-amber',
  done_local: 'bg-accent-green',
  error: 'bg-accent-red',
};

function bankFromFilename(filename: string): { name: string; code: string | null } {
  const lower = filename.toLowerCase();
  if (lower.includes('tinkoff') || lower.includes('тинь') || lower.includes('tbank') || lower.includes('т-банк')) {
    return { name: 'Т-Банк', code: 'tbank' };
  }
  if (lower.includes('sber') || lower.includes('сбер')) {
    return { name: 'Сбер', code: 'sber' };
  }
  if (lower.includes('alfa') || lower.includes('альф')) {
    return { name: 'Альфа-Банк', code: 'alfa' };
  }
  if (lower.includes('vtb') || lower.includes('втб')) {
    return { name: 'ВТБ', code: 'vtb' };
  }
  if (lower.includes('gpb') || lower.includes('газпром')) {
    return { name: 'Газпромбанк', code: 'gazprombank' };
  }
  if (lower.includes('ozon') || lower.includes('озон')) {
    return { name: 'Озон Банк', code: 'ozon' };
  }
  if (lower.includes('yandex') || lower.includes('яндекс')) {
    return { name: 'Яндекс Банк', code: 'yandex' };
  }
  return { name: '?', code: null };
}

export function QueuePanel({
  origin,
  onClose,
  onResume,
  onOpenMapping,
}: {
  origin: { x: number; y: number };
  onClose: () => void;
  onResume: (sessionId: number) => void;
  onOpenMapping: (sessionId: number) => void;
}) {
  const queryClient = useQueryClient();
  const sessionsQuery = useQuery({
    queryKey: ['import-sessions'],
    queryFn: async () => {
      const { getImportSessions } = await import('@/lib/api/imports');
      return getImportSessions();
    },
    refetchInterval: 2000,
  });
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });

  const sessions = sessionsQuery.data?.sessions ?? [];
  const accounts = accountsQuery.data ?? [];

  const [openId, setOpenId] = useState<number | null>(null);

  // ESC closes
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const deleteMut = useMutation({
    mutationFn: deleteImportSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Выписка удалена из очереди');
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось удалить'),
  });

  const summaryParts: string[] = [];
  const ready = sessions.filter((s) => classifySession(s) === 'done_local').length;
  const errors = sessions.filter((s) => classifySession(s) === 'error').length;
  if (sessions.length) summaryParts.push(`${sessions.length} в работе`);
  if (ready) summaryParts.push(`${ready} готова к импорту`);
  if (errors) summaryParts.push(`${errors} ошибок`);

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="queue-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1, transition: { duration: 0.18 } }}
        exit={{ opacity: 0, transition: { duration: 0.12 } }}
        className="fixed inset-0 z-[9000] bg-ink/30 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div
        key="queue-wrap"
        className="pointer-events-none fixed inset-0 z-[9001] flex items-center justify-center p-4"
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.05 }}
          animate={{ opacity: 1, scale: 1, transition: { duration: 0.32, ease: [0.16, 0.84, 0.3, 1] } }}
          exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.14 } }}
          // Anchor the scale animation at the click origin so the modal "grows" from the pill.
          style={{
            transformOrigin: `${origin.x - window.innerWidth / 2}px ${origin.y - window.innerHeight / 2}px`,
          }}
          className="pointer-events-auto flex max-h-[85vh] w-[min(820px,92vw)] flex-col overflow-hidden rounded-3xl border border-line bg-bg-surface shadow-modal"
          onClick={(e) => e.stopPropagation()}
        >
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-line px-5 py-4">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-white">
            <FileText className="size-3.5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold text-ink">Очередь выписок</div>
            <div className="mt-0.5 truncate text-xs text-ink-3">
              {summaryParts.length ? summaryParts.join(' · ') : 'Очередь пуста'}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid size-8 place-items-center rounded-full text-ink-3 transition hover:bg-ink/5"
          >
            <X className="size-3.5" />
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-auto px-3 py-2">
          {sessionsQuery.isLoading ? (
            <div className="grid h-32 place-items-center text-xs text-ink-3">
              <Loader2 className="size-4 animate-spin" />
            </div>
          ) : sessions.length === 0 ? (
            <div className="grid h-32 place-items-center text-xs text-ink-3">
              Нет выписок. Загрузи CSV/XLSX/PDF — появится здесь.
            </div>
          ) : (
            sessions.map((s) => {
              const classified = classifySession(s);
              const isOpen = openId === s.id;
              return (
                <QueueRow
                  key={s.id}
                  session={s}
                  classified={classified}
                  accounts={accounts}
                  isOpen={isOpen}
                  onToggle={() => setOpenId(isOpen ? null : s.id)}
                  onResume={() => {
                    onResume(s.id);
                    onClose();
                  }}
                  onOpenMapping={() => {
                    onOpenMapping(s.id);
                    onClose();
                  }}
                  onDelete={() => deleteMut.mutate(s.id)}
                  deleting={deleteMut.isPending}
                />
              );
            })
          )}
        </div>
        </motion.div>
      </div>
    </AnimatePresence>,
    document.body,
  );
}

// ──────────────────────────────────────────────────────────────────────────

function QueueRow({
  session,
  classified,
  accounts,
  isOpen,
  onToggle,
  onResume,
  onOpenMapping,
  onDelete,
  deleting,
}: {
  session: ImportSessionListItem;
  classified: QueueStatus;
  accounts: Account[];
  isOpen: boolean;
  onToggle: () => void;
  onResume: () => void;
  onOpenMapping: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  // Prefer bank info from the assigned account (always reliable when set);
  // fall back to filename heuristic for sessions that haven't been assigned.
  const accountForSession = session.account_id != null
    ? accounts.find((a) => a.id === session.account_id) ?? null
    : null;
  const fromFilename = bankFromFilename(session.filename);
  const bankCode = accountForSession?.bank?.code ?? fromFilename.code ?? null;
  const bankName = accountForSession?.bank?.name ?? fromFilename.name;

  return (
    <div
      className={cnRow(isOpen)}
      style={{ marginTop: isOpen ? 6 : 0, marginBottom: isOpen ? 6 : 0 }}
    >
      <div className="grid w-full grid-cols-[14px_36px_1fr_auto_14px] items-center gap-3 px-3 py-3.5">
        <span
          className={`size-2.5 rounded-full ${STATUS_DOT[classified]}`}
          title={STATUS_LABEL[classified]}
          style={{ boxShadow: '0 0 0 3px rgba(0,0,0,0.04)' }}
        />
        <BankIcon bank={bankName} code={bankCode} size={36} />
        <div className="min-w-0">
          <div className="truncate font-mono text-[13px] font-medium text-ink">
            {session.filename}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-3">
            <span>{bankName}</span>
            <span>·</span>
            <QueueAccountSelector
              session={session}
              accounts={accounts}
            />
            <span>·</span>
            <span>{session.row_count} оп.</span>
          </div>
        </div>

        {/* Action slot */}
        <div className="flex min-w-[160px] justify-end">
          {classified === 'parsing' ? (
            <span className="inline-flex items-center gap-1.5 rounded-pill bg-accent-violet-soft px-2.5 py-1 text-[11px] font-medium text-accent-violet">
              <Loader2 className="size-3 animate-spin" />
              Распознаём…
            </span>
          ) : classified === 'error' ? (
            <button
              type="button"
              onClick={onOpenMapping}
              className="rounded-lg bg-accent-red px-3.5 py-1.5 text-xs font-medium text-white transition hover:opacity-90"
            >
              Открыть
            </button>
          ) : classified === 'done_local' ? (
            <button
              type="button"
              onClick={onResume}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-green px-3.5 py-1.5 text-xs font-medium text-white transition hover:opacity-90"
            >
              <Check className="size-3" />
              Импортировать
            </button>
          ) : (
            <button
              type="button"
              onClick={onResume}
              className="inline-flex items-center gap-1.5 rounded-lg bg-ink px-3.5 py-1.5 text-xs font-medium text-white transition hover:bg-ink-2"
            >
              <ArrowRight className="size-3" />
              {classified === 'progress' ? 'Продолжить разбор' : 'Начать разбор'}
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={onToggle}
          title={isOpen ? 'Свернуть' : 'Развернуть подробности'}
          className="grid size-6 place-items-center rounded text-ink-3 transition hover:bg-bg-surface2"
        >
          {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        </button>
      </div>

      {isOpen ? (
        <div className="overflow-hidden">
          <RowDetail
            session={session}
            classified={classified}
            onDelete={onDelete}
            onOpenMapping={onOpenMapping}
            deleting={deleting}
          />
        </div>
      ) : null}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// QueueAccountSelector — chip-button opening a popover with account list +
// "Создать новый счёт" entry (opens the existing AccountDialog).
function QueueAccountSelector({
  session,
  accounts,
}: {
  session: ImportSessionListItem;
  accounts: Account[];
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number; width: number } | null>(null);
  const [creating, setCreating] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const popRef = useRef<HTMLDivElement | null>(null);

  const account = session.account_id != null
    ? accounts.find((a) => a.id === session.account_id) ?? null
    : null;
  const isUnknown = !account;

  const updateCoords = () => {
    if (!btnRef.current) return;
    const r = btnRef.current.getBoundingClientRect();
    setCoords({ top: r.bottom + 4, left: r.left, width: r.width });
  };

  useLayoutEffect(() => {
    if (open) updateCoords();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (btnRef.current?.contains(e.target as Node)) return;
      if (popRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onScroll = () => updateCoords();
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onScroll);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onScroll);
    };
  }, [open]);

  const assignMut = useMutation({
    mutationFn: (accountId: number) => assignSessionAccount(session.id, accountId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Счёт привязан');
      setOpen(false);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось привязать счёт'),
  });

  const createMut = useMutation({
    mutationFn: (payload: CreateAccountPayload) => createAccount(payload),
    onSuccess: async (acc: Account) => {
      await queryClient.invalidateQueries({ queryKey: ['accounts'] });
      assignMut.mutate(acc.id);
      setCreating(false);
    },
    onError: (e: Error) => {
      toast.error(e.message || 'Не удалось создать счёт');
      setCreating(false);
    },
  });

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={
          isUnknown
            ? 'inline-flex items-center gap-1.5 rounded-md border border-accent-amber bg-accent-amber-soft px-2 py-1 text-[11px] font-medium text-accent-amber transition'
            : 'inline-flex items-center gap-1.5 rounded-md border border-line bg-bg-surface2 px-2 py-1 text-[11px] font-medium text-ink-2 transition hover:bg-bg-surface'
        }
      >
        <Wallet className="size-3" />
        <span className="font-mono max-w-[200px] truncate">
          {account ? account.name : 'счёт не выбран'}
        </span>
        <ChevronDown className="size-2.5" />
      </button>

      {open && coords ? createPortal(
        <div
          ref={popRef}
          onClick={(e) => e.stopPropagation()}
          style={{ top: coords.top, left: coords.left, minWidth: Math.max(coords.width, 280) }}
          className="fixed z-[9700] flex max-h-80 flex-col overflow-hidden rounded-xl border border-line bg-bg-surface shadow-modal"
        >
          <div className="border-b border-line px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-ink-3">
            Привязать выписку к счёту
          </div>
          <div className="flex-1 overflow-auto py-1">
            {accounts.length === 0 ? (
              <div className="px-3 py-2 text-xs text-ink-3">Нет счетов в системе.</div>
            ) : null}
            {accounts.map((a) => {
              const sel = a.id === session.account_id;
              return (
                <button
                  key={a.id}
                  type="button"
                  disabled={assignMut.isPending}
                  onClick={() => assignMut.mutate(a.id)}
                  className={
                    'flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs transition disabled:opacity-60 ' +
                    (sel ? 'bg-bg-surface2 font-medium' : 'hover:bg-bg-surface2')
                  }
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <BankIcon bank={a.bank?.name ?? null} code={a.bank?.code ?? null} size={20} />
                    <span className="truncate">{a.name}</span>
                  </span>
                  {sel ? <Check className="size-3" /> : null}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="flex w-full items-center gap-2 border-t border-line bg-bg-surface2 px-3 py-2.5 text-left text-xs font-medium text-ink transition hover:bg-line/40"
          >
            <Plus className="size-3 text-ink-3" /> Создать новый счёт…
          </button>
        </div>,
        document.body,
      ) : null}

      <AccountDialog
        open={creating}
        mode="create"
        isSubmitting={createMut.isPending}
        onClose={() => setCreating(false)}
        onSubmit={(values) => createMut.mutate(values)}
      />
    </>
  );
}

function cnRow(isOpen: boolean) {
  return [
    'transition',
    isOpen
      ? 'rounded-2xl border border-line bg-bg-surface'
      : 'border-b border-line',
  ].join(' ');
}

// ──────────────────────────────────────────────────────────────────────────
// Expanded row detail — counterparty preview, error helper, etc.

function RowDetail({
  session,
  classified,
  onDelete,
  onOpenMapping,
  deleting,
}: {
  session: ImportSessionListItem;
  classified: QueueStatus;
  onDelete: () => void;
  onOpenMapping: () => void;
  deleting: boolean;
}) {
  if (classified === 'parsing') {
    return (
      <div className="px-4 pb-4 text-center text-xs text-ink-3">
        Файл сейчас распознаётся. Откроется автоматически, когда будет готов.
      </div>
    );
  }
  if (classified === 'error') {
    return (
      <div className="p-4">
        <div className="flex items-start gap-3 rounded-xl border border-accent-red-soft bg-bg-surface p-3.5">
          <span className="grid size-7 shrink-0 place-items-center rounded-md bg-accent-red-soft text-accent-red">
            <span className="text-sm">!</span>
          </span>
          <div className="flex-1">
            <div className="text-sm font-semibold text-ink">Не смог разобрать формат</div>
            <p className="mt-1 text-xs leading-5 text-ink-2">
              Открой сопоставление колонок, чтобы помочь системе распознать таблицу.
            </p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={onOpenMapping}
                className="rounded-lg bg-ink px-3.5 py-1.5 text-xs font-medium text-white"
              >
                Сопоставить колонки
              </button>
              <button
                type="button"
                onClick={onDelete}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-transparent px-3.5 py-1.5 text-xs text-ink-3 transition hover:bg-bg-surface2 disabled:opacity-60"
              >
                <Trash2 className="size-3" /> Удалить
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
  return (
    <>
      <SessionMetaBlock sessionId={session.id} />
      <CounterpartyPreview sessionId={session.id} />
    </>
  );
}

// Pulls full session details (parse_settings) so we can surface contract
// number / statement account number — these fields are NOT in the lighter
// ImportSessionListItem shape used by the queue.
function SessionMetaBlock({ sessionId }: { sessionId: number }) {
  const sessionQuery = useQuery({
    queryKey: ['imports', 'session', sessionId],
    queryFn: () => getImportSession(sessionId),
  });
  if (sessionQuery.isLoading || !sessionQuery.data) return null;
  const ps = (sessionQuery.data.parse_settings ?? {}) as Record<string, unknown>;
  const contract = typeof ps.contract_number === 'string' ? ps.contract_number : null;
  const accNum = typeof ps.statement_account_number === 'string' ? ps.statement_account_number : null;
  if (!contract && !accNum) return null;
  return (
    <div className="mb-2 px-4 pt-3">
      <div className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[10.5px] text-ink-3">
        {contract ? <span>Договор № {contract}</span> : null}
        {accNum   ? <span>Счёт № {accNum}</span> : null}
      </div>
    </div>
  );
}

// Aggregates counterparties from preview rows by `normalized_data.brand` /
// `normalized_data.counterparty_name`. Keeps the panel self-contained — no
// extra backend endpoint required.
function CounterpartyPreview({ sessionId }: { sessionId: number }) {
  const previewQuery = useQuery({
    queryKey: ['imports', 'preview', sessionId],
    queryFn: () => getImportPreview(sessionId),
  });
  const clustersQuery = useQuery({
    queryKey: ['imports', 'bulk-clusters', sessionId],
    queryFn: () => getBulkClusters(sessionId),
  });

  if (previewQuery.isLoading || clustersQuery.isLoading) {
    return (
      <div className="grid h-24 place-items-center text-xs text-ink-3">
        <Loader2 className="size-3.5 animate-spin" />
      </div>
    );
  }
  if (!previewQuery.data) return null;

  const groups = aggregateCounterparties(previewQuery.data, clustersQuery.data ?? null);

  if (groups.length === 0) {
    return (
      <div className="px-4 pb-4 text-center text-xs text-ink-3">
        Контрагенты ещё не выделены — продолжи разбор, и они появятся.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-bg-surface">
      <div className="border-b border-line px-3.5 py-2 text-[11px] uppercase tracking-wider text-ink-3">
        Контрагенты в выписке
      </div>
      {groups.slice(0, 6).map((g, i) => (
        <div
          key={g.label + i}
          className="grid grid-cols-[22px_1fr_auto_auto] items-center gap-2.5 border-b border-line px-3.5 py-2 text-[12.5px] last:border-b-0"
        >
          <span className="grid size-5 place-items-center rounded-md bg-bg-surface2 text-[10px] font-semibold">
            {g.label.charAt(0).toUpperCase()}
          </span>
          <span className="truncate">{g.label}</span>
          <span className="text-[11px] text-ink-3">{g.count} оп.</span>
          <Chip tone="line">{g.category ?? 'Категория не выбрана'}</Chip>
        </div>
      ))}
    </div>
  );
}

function aggregateCounterparties(
  preview: ImportPreviewResponse,
  clusters: BulkClustersResponse | null,
) {
  const counterpartyById = new Map<number, string>();
  if (clusters?.counterparty_groups) {
    for (const g of clusters.counterparty_groups) {
      counterpartyById.set(g.counterparty_id, g.counterparty_name);
    }
  }

  const buckets = new Map<string, { label: string; count: number; category: string | null }>();

  for (const row of preview.rows) {
    const nd = (row.normalized_data ?? {}) as Record<string, unknown>;
    const cpName =
      (typeof nd.counterparty_name === 'string' && nd.counterparty_name) ||
      (typeof nd.brand === 'string' && nd.brand) ||
      (typeof nd.merchant === 'string' && nd.merchant) ||
      null;
    if (!cpName) continue;
    const key = cpName.trim();
    if (!key) continue;
    const existing = buckets.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      buckets.set(key, { label: key, count: 1, category: null });
    }
  }

  return Array.from(buckets.values()).sort((a, b) => b.count - a.count);
}
