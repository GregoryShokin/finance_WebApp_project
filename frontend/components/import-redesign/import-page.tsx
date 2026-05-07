'use client';

/**
 * Main import screen — warm-design redesign (2026-04-30).
 *
 * Composition:
 *   ImportActionsBar   ── shapes the top: upload, queue pill, commit button
 *   ImportStatusCard   ── progress / counts for current statement
 *   ClusterGrid        ── bulk-cluster cards w/ modal expansion
 *   AttentionFeed      ── singles list, per-row inline editing + traffic light
 *   ImportFabCluster   ── floating actions bottom-right
 *   QueuePanel         ── modal opened from action bar pill or FAB pill
 *   MappingModal       ── recovery flow for sessions with parse errors
 */

import { useRef, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { useAuth } from '@/hooks/use-auth';
import { getAccounts } from '@/lib/api/accounts';
import {
  commitImport,
  commitImportQueueConfirmed,
  getImportSession,
  unexcludeImportRow,
  unparkImportRow,
  uploadImportFile,
} from '@/lib/api/imports';
import { getBanks } from '@/lib/api/banks';
import { ApiError } from '@/lib/api/client';
import { formatRateLimitErrorUpload } from '@/lib/api/rate-limit-error';
import { validateUploadSize } from '@/lib/upload/limits';
import { BankSupportRequestModal } from '@/components/accounts/bank-support-request-form';
import { Button } from '@/components/ui/button';

import { ImportActionsBar } from './import-actions-bar';
import { ImportStatusCard } from './import-status-card';
import { ClusterGrid } from './cluster-grid';
import { AttentionFeed } from './attention-feed';
import { ChronologicalView } from './chronological-view';
import { ImportFabCluster } from './import-fab-cluster';
import { QueuePanel } from './queue-panel';
import { MappingModal } from './mapping-modal';
import { DuplicateModal } from './duplicate-modal';
import { CreateAccountFromImportModal } from './create-account-from-import-modal';
import { AccountCandidatesPickerModal } from './account-candidates-picker-modal';
import { AccountTypeConfirmModal } from './account-type-confirm-modal';
import { useActiveImportSession } from './use-active-session';
import { useImportQueue } from './use-import-queue';
import { FlyToFabProvider } from './fly-to-fab-context';
import { fmtRubAbs } from './format';
import type { ImportUploadResponse } from '@/types/import';
import type { Bank, ExtractorStatus } from '@/types/account';

export function ImportPage() {
  useAuth(); // keep auth hook mounted (token refresh side effects)
  const queryClient = useQueryClient();

  const {
    sessions,
    activeSessionId,
    setActive,
    preview,
    isLoadingPreview,
    clusters,
  } = useActiveImportSession();

  // v1.23: unified queue. Cross-session rows + clusters drive chronological
  // view; cluster mode remains per-session for now (bulk-apply still
  // session-scoped — queue-level cluster bulk-apply is a follow-up).
  const queue = useImportQueue();

  const queuePillRef = useRef<HTMLButtonElement | null>(null);
  const [queueOpen, setQueueOpen] = useState<{ x: number; y: number } | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<number | null>(null);

  // Ph7b: cluster vs chronological view. Persisted across reloads so the
  // user's preference sticks. Default 'chronological' — that's the new
  // primary UX (Brand registry plan §7) and the cluster grid stays as an
  // opt-in fallback for users who want the bulk-by-brand workflow.
  const [importView, setImportView] = useState<'clusters' | 'chronological'>(
    () => {
      if (typeof window === 'undefined') return 'chronological';
      const stored = window.localStorage.getItem('import.view');
      return stored === 'clusters' ? 'clusters' : 'chronological';
    },
  );
  const setImportViewPersistent = (v: 'clusters' | 'chronological') => {
    setImportView(v);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('import.view', v);
    }
  };

  // Этап 0.5: duplicate-statement detection state.
  // `pendingFile` is needed because the user may pick "Загрузить как новую"
  // in the modal — at that point we have to re-fire the upload with
  // forceNew=true, but the original `File` object is no longer in the
  // mutation's variables (mutate() was called once and resolved).
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [duplicateState, setDuplicateState] = useState<ImportUploadResponse | null>(null);
  // Этап 1 Шаг 1.6: bank-unsupported intercept on upload error.
  // When the backend rejects with `code='bank_unsupported'`, we open the
  // BankSupportRequestModal pre-filled with the bank that was matched —
  // skipping the generic toast so the user lands directly on the action
  // (request support) instead of just seeing «не поддерживается» and
  // wondering what to do.
  const [unsupportedBank, setUnsupportedBank] = useState<Bank | null>(null);

  // Auto-account-recognition Шаг 3 (2026-05-06).
  // Two new branches in `uploadMut.onSuccess`:
  //   • requires_account_creation=true → open CreateAccountFromImportModal,
  //     pre-filled with bank_id + account_type_hint + contract/statement.
  //   • account_candidates.length >= 2 → open AccountCandidatesPickerModal
  //     so the user picks one of N matching accounts (or routes to the
  //     create-account modal as escape hatch).
  // Both states carry the upload payload so the modals can call
  // assignSessionAccount(sessionId, …) themselves.
  const [createAccountState, setCreateAccountState] = useState<ImportUploadResponse | null>(null);
  const [candidatesState, setCandidatesState] = useState<ImportUploadResponse | null>(null);
  // Confirm-first path: when the extractor knows enough (bank + maybe type),
  // we ask "Создать «<Bank> <Type>»?" instead of opening the full form.
  // The user clicks once → account is created and attached. "Изменить
  // параметры" / "Другое" routes them to createAccountState (full form).
  // confirmState carries the upload payload (or a session-rehydrated equivalent
  // for the queue-panel path) so the modal has everything it needs.
  const [confirmState, setConfirmState] = useState<ImportUploadResponse | null>(null);

  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const hasSupportedAccount = useMemo(() => {
    const accounts = accountsQuery.data ?? [];
    if (accounts.length === 0) return null;
    return accounts.some((a) => a.bank?.extractor_status === 'supported');
  }, [accountsQuery.data]);
  // Этап 1 Шаг 1.6 — pre-upload disclaimer. Distinct from EmptyState's
  // "no supported account at all" branch: this fires when the user has
  // BOTH supported and unsupported-bank accounts. Without the warning,
  // a user with e.g. Сбер + Альфа might upload an Альфа statement and
  // see a 415 only AFTER picking the file — frustrating in production
  // when the upload is 25 MB.
  const unsupportedAccountBanks = useMemo(() => {
    const accounts = accountsQuery.data ?? [];
    const seen = new Map<number, { id: number; name: string }>();
    for (const a of accounts) {
      if (a.bank && a.bank.extractor_status !== 'supported' && !seen.has(a.bank.id)) {
        seen.set(a.bank.id, { id: a.bank.id, name: a.bank.name });
      }
    }
    return Array.from(seen.values());
  }, [accountsQuery.data]);

  const uploadMut = useMutation({
    mutationFn: ({ file, forceNew }: { file: File; forceNew?: boolean }) =>
      uploadImportFile({ file, delimiter: ',', forceNew }),
    onSuccess: async (res) => {
      // Этап 0.5: duplicate detection. Don't auto-setActive on a `choose` /
      // `warn` response — surface the modal first so the user picks the
      // resolution. `force_new=true` retry path skips this branch because
      // backend never returns action_required when force_new is set.
      if (res.action_required === 'choose' || res.action_required === 'warn') {
        setDuplicateState(res);
        return;
      }

      // Auto-account-recognition Шаг 3 — branches that take precedence over
      // the auto-setActive path. The session is already created on the
      // backend, but it's better to resolve account binding BEFORE pushing
      // the user into the preview screen — the queue + AttentionFeed are
      // confusing without an account attached.
      //
      // Order matters: requires_account_creation wins over candidates,
      // because it's the unambiguous "no account exists" signal. Candidates
      // fire only when 2+ existing accounts could match.
      if (res.requires_account_creation && res.suggested_bank_id) {
        await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
        // Inline-prompt UX (Шаг 4): instead of any popup at upload time, we
        // surface the «Это <Bank> <Type>?» question inline in the queue row.
        // The session is already created on the backend with account_id=null
        // and bank_code/account_type_hint stamped in parse_settings; the
        // queue picks it up on next poll and renders the prompt.
        toast.success(`Загружено: ${res.filename}`, {
          description: 'Распознан банк — выбери счёт в очереди',
        });
        setPendingFile(null);
        return;
      }
      if (res.account_candidates && res.account_candidates.length >= 2) {
        await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
        setCandidatesState(res);
        setPendingFile(null);
        return;
      }

      // Friendly toast when Level 1/2/3 produced an auto-attach — surface the
      // match reason so the user understands why the session was attached
      // (e.g. "по контракту" vs "единственный счёт банка X"). Skipped when
      // the upload didn't auto-resolve — the regular toast covers that case.
      if (res.suggested_account_id && res.suggested_account_match_reason) {
        toast.success(`Загружено: ${res.filename}`, {
          description: res.suggested_account_match_reason,
        });
      } else {
        toast.success(`Загружено: ${res.filename}`);
      }
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      setActive(res.session_id);
      setPendingFile(null);
    },
    onError: (e: Error) => {
      setPendingFile(null);
      // Bank-unsupported branch: open the request-support modal instead of
      // a toast. The modal pre-fills the bank fields so the user only types
      // an optional note. Other errors fall through to formatUploadError.
      if (e instanceof ApiError && e.payload?.code === 'bank_unsupported') {
        const bankId = typeof e.payload.bank_id === 'number' ? e.payload.bank_id : null;
        const bankName = typeof e.payload.bank_name === 'string' ? e.payload.bank_name : '';
        const status: ExtractorStatus =
          (typeof e.payload.extractor_status === 'string' &&
            (e.payload.extractor_status === 'pending' ||
              e.payload.extractor_status === 'in_review' ||
              e.payload.extractor_status === 'broken'))
            ? e.payload.extractor_status
            : 'pending';
        if (bankId !== null) {
          setUnsupportedBank({
            id: bankId,
            name: bankName,
            code: '',
            bik: null,
            is_popular: false,
            extractor_status: status,
            extractor_last_tested_at: null,
            extractor_notes: null,
          });
          return;
        }
      }
      toast.error(formatUploadError(e));
    },
  });

  // Pre-upload guard: bounce oversized or wrong-extension files before they
  // hit the network. Backend has the same check (defense-in-depth) — this is
  // purely UX so the user doesn't wait on a 25 MB upload to be told «too big».
  function handleSelectFile(file: File) {
    const result = validateUploadSize(file);
    if (!result.ok) {
      toast.error(result.message);
      return;
    }
    setPendingFile(file);
    uploadMut.mutate({ file });
  }

  function handleDuplicateOpenExisting() {
    if (duplicateState?.session_id) {
      setActive(duplicateState.session_id);
    }
    setDuplicateState(null);
    setPendingFile(null);
  }

  function handleDuplicateForceNew() {
    if (pendingFile) {
      uploadMut.mutate({ file: pendingFile, forceNew: true });
    }
    setDuplicateState(null);
    // pendingFile cleared in onSuccess of the retry mutation
  }

  function handleDuplicateCancel() {
    setDuplicateState(null);
    setPendingFile(null);
  }

  const commitMut = useMutation({
    mutationFn: (sessionId: number) => commitImport(sessionId, true),
    onSuccess: async (res) => {
      toast.success(`Импортировано: ${res.imported_count} операций`);
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      await queryClient.invalidateQueries({ queryKey: ['imports', 'preview', res.session_id] });
      // Committed rows are excluded from build_bulk_clusters — without this
      // invalidation the ClusterGrid shows stale cards for committed rows.
      await queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters', res.session_id] });
      await queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status', res.session_id] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось импортировать'),
  });

  // v1.23 — queue-mode commit: one button commits all confirmed rows
  // across every active session of the user (variant C). Sessions whose
  // last row is committed auto-flip to status='committed' on the backend
  // and disappear from the queue on the next refetch.
  const commitQueueMut = useMutation({
    mutationFn: () => commitImportQueueConfirmed(),
    onSuccess: async (res) => {
      const sessionWord =
        res.sessions.length === 1 ? 'выписки' : `${res.sessions.length} выписок`;
      toast.success(
        `Импортировано ${res.totals.imported} ${
          res.totals.imported === 1 ? 'операция' : 'операций'
        } из ${sessionWord}`,
      );
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      // Prefix-match invalidates both queue and per-session preview/clusters.
      await queryClient.invalidateQueries({ queryKey: ['imports', 'preview'] });
      await queryClient.invalidateQueries({ queryKey: ['imports', 'bulk-clusters'] });
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось импортировать'),
  });

  // Reset session — frontend-only batch: unpark + unexclude every row that
  // was moved off the active list. Category / counterparty edits remain
  // committed to the backend (full reset would require a dedicated endpoint).
  const resetMut = useMutation({
    mutationFn: async () => {
      if (!preview) return { count: 0 };
      const targets = preview.rows.filter((r) => r.status === 'parked' || r.status === 'skipped');
      for (const r of targets) {
        if (r.status === 'parked')  await unparkImportRow(r.id);
        if (r.status === 'skipped') await unexcludeImportRow(r.id);
      }
      return { count: targets.length };
    },
    onSuccess: async (res) => {
      if (res.count === 0) toast.info('Нет отложенных или исключённых строк');
      else toast.success(`Сброшено: ${res.count} строк возвращены в обработку`);
      if (activeSessionId) {
        await queryClient.invalidateQueries({ queryKey: ['imports', 'preview', activeSessionId] });
        await queryClient.invalidateQueries({ queryKey: ['imports', 'moderation-status', activeSessionId] });
      }
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось сбросить'),
  });

  const totalRows = preview?.summary.total_rows ?? 0;
  const readyRows = preview?.summary.ready_rows ?? 0;

  // Count only rows that actually appear in the attention feed:
  // warning status, not in any cluster, not a transfer/duplicate/parked/skipped.
  const reviewRows = useMemo(() => {
    if (!preview) return 0;
    const inCluster = new Set<number>();
    for (const fc of clusters?.fingerprint_clusters ?? []) {
      for (const id of fc.row_ids) inCluster.add(id);
    }
    return preview.rows.filter((r) => {
      if (r.status === 'ready' || r.status === 'committed' || r.status === 'duplicate') return false;
      if (r.status === 'parked' || r.status === 'skipped') return false;
      if (inCluster.has(r.id)) return false;
      const nd = r.normalized_data as Record<string, unknown> | undefined;
      if (nd?.transfer_match || nd?.operation_type === 'transfer') return false;
      return true;
    }).length;
  }, [preview, clusters]);

  const queueOk = sessions.filter((s) => s.row_count > 0 && s.ready_count === s.row_count).length;
  const queueExc = sessions.filter((s) => s.auto_preview_status === 'failed' || s.status === 'failed').length;
  const queueSnz = sessions.length - queueOk - queueExc;

  let readySumNumeric = 0;
  if (preview) {
    for (const r of preview.rows) {
      if (r.status !== 'ready') continue;
      const nd = r.normalized_data as Record<string, unknown> | undefined;
      const v = (nd?.amount as string | number | null) ?? r.raw_data?.amount ?? null;
      const n = typeof v === 'string' ? Number(v) : (v as number | null);
      if (Number.isFinite(n)) readySumNumeric += Math.abs(n as number);
    }
  }
  const readySum = readyRows > 0 ? fmtRubAbs(readySumNumeric) : null;

  // Queue → confirm rehydrate. When the user presses «Начать разбор» on a
  // session that's still without an account (Шаг 3 was added after these
  // sessions were uploaded, OR the user cancelled the modal earlier), we
  // re-derive bank_code / account_type_hint / contract_number /
  // statement_account_number from session.parse_settings.extraction and
  // open the same confirm modal as on fresh upload.
  async function resumeSession(sessionId: number) {
    console.log('[resumeSession] start', sessionId);
    const list = sessions.find((s) => s.id === sessionId);
    console.log('[resumeSession] found in list', { hasAccount: list?.account_id != null });
    // Account already attached → straight into preview.
    if (list?.account_id != null) {
      setActive(sessionId);
      return;
    }
    try {
      const full = await getImportSession(sessionId);
      const ps = (full.parse_settings ?? {}) as { extraction?: Record<string, unknown> };
      const ext = (ps.extraction ?? {}) as Record<string, unknown>;
      const bankCode = (ext.bank_code as string | null | undefined) ?? null;
      const accountTypeHint = (ext.account_type_hint as string | null | undefined) ?? null;
      const contractNumber = (ext.contract_number as string | null | undefined) ?? null;
      const statementAccountNumber = (ext.statement_account_number as string | null | undefined) ?? null;
      console.log('[resumeSession] hydrated', { bankCode, accountTypeHint, contractNumber, statementAccountNumber });

      if (bankCode && bankCode !== 'unknown') {
        // Resolve bank_id by code via the same cached banks list the modal uses.
        const banks = await queryClient.fetchQuery({
          queryKey: ['banks', { supportedOnly: false }],
          queryFn: () => getBanks(undefined, { supportedOnly: false }),
          staleTime: 60_000,
        });
        const bank = banks.find((b) => b.code === bankCode);
        console.log('[resumeSession] resolved bank', { bank });
        if (bank) {
          // Synthesize an ImportUploadResponse-shaped payload so the existing
          // confirm/create modals can consume it without code changes.
          // Required fields filled with safe defaults — the modals read only
          // session_id / suggested_bank_id / account_type_hint /
          // contract_number / statement_account_number / account_candidates.
          const synthetic: ImportUploadResponse = {
            session_id: sessionId,
            filename: full.filename,
            source_type: full.source_type,
            status: full.status,
            detected_columns: full.detected_columns ?? [],
            sample_rows: [],
            total_rows: 0,
            extraction: ext,
            detection: { selected_table: null, available_tables: [], field_mapping: {}, field_confidence: {}, field_reasons: {}, column_analysis: [], suggested_date_formats: [], overall_confidence: 0, confidence_label: 'low', unresolved_fields: [] },
            suggested_account_id: null,
            contract_number: contractNumber,
            contract_match_reason: null,
            contract_match_confidence: null,
            statement_account_number: statementAccountNumber,
            statement_account_match_reason: null,
            statement_account_match_confidence: null,
            bank_code: bankCode,
            account_type_hint: accountTypeHint,
            suggested_account_match_reason: null,
            suggested_account_match_confidence: null,
            suggested_bank_id: bank.id,
            account_candidates: [],
            requires_account_creation: true,
          };
          console.log('[resumeSession] opening confirm modal', synthetic);
          setConfirmState(synthetic);
          return;
        }
      }
    } catch (e) {
      // Fall through: unable to hydrate parse_settings → fall back to the
      // legacy "open in queue" behaviour so the user isn't stuck.
      console.error('Failed to hydrate session for confirm modal', e);
    }
    console.log('[resumeSession] fallback setActive', sessionId);
    setActive(sessionId);
  }

  function openQueueAtPill() {
    const el = queuePillRef.current;
    if (!el) {
      setQueueOpen({ x: window.innerWidth / 2, y: 120 });
      return;
    }
    const r = el.getBoundingClientRect();
    setQueueOpen({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
  }

  return (
    <FlyToFabProvider>
    <div className="relative flex-1 pb-32 lg:pr-24">
      <ImportActionsBar
        queuePillRef={queuePillRef}
        uploading={uploadMut.isPending}
        committing={commitMut.isPending || commitQueueMut.isPending}
        resetting={resetMut.isPending}
        resetEnabled={activeSessionId !== null && !!preview}
        onUpload={handleSelectFile}
        onOpenQueue={openQueueAtPill}
        // v1.23: prefer the unified queue commit. Falls back to legacy
        // per-session commit only when there are no queue rows but there
        // IS an active session (legacy `?session=N` URL deep-link).
        onCommit={() => {
          if (queue.rows.length > 0) {
            commitQueueMut.mutate();
          } else if (activeSessionId !== null) {
            commitMut.mutate(activeSessionId);
          }
        }}
        onReset={() => {
          if (!confirm('Сбросить сессию: вернуть все отложенные и исключённые строки обратно в обработку?')) return;
          resetMut.mutate();
        }}
        queueCount={sessions.length}
        queueOk={queueOk}
        queueSnz={queueSnz}
        queueExc={queueExc}
        readyCount={queue.summary?.ready_rows ?? readyRows}
        readySum={readySum}
      />

      {hasSupportedAccount && unsupportedAccountBanks.length > 0 && (
        <UnsupportedBankBanner
          banks={unsupportedAccountBanks}
          onRequestSupport={(bank) =>
            setUnsupportedBank({
              id: bank.id,
              name: bank.name,
              code: '',
              bik: null,
              is_popular: false,
              extractor_status: 'pending',
              extractor_last_tested_at: null,
              extractor_notes: null,
            })
          }
        />
      )}

      <div className="mt-5 space-y-3.5">
        {/*
          Queue mode renders the chronological view ALWAYS when there are
          queue rows, independent of `activeSessionId`. EmptyState only
          when there are no queue rows AND no active session.
        */}
        {queue.rows.length === 0 && activeSessionId === null ? (
          <EmptyState hasSupportedAccount={hasSupportedAccount} />
        ) : (queue.isLoadingPreview && queue.rows.length === 0)
            && (isLoadingPreview && !preview) ? (
          <div className="surface-card grid h-48 place-items-center text-xs text-ink-3">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : (
          <>
            <ImportStatusCard
              totalRows={queue.summary?.total_rows ?? totalRows}
              readyRows={queue.summary?.ready_rows ?? readyRows}
              reviewRows={Math.max(
                (queue.summary?.warning_rows ?? 0) + (queue.summary?.error_rows ?? 0),
                reviewRows,
                0,
              )}
            />
            <div className="flex items-center justify-end">
              <div
                role="tablist"
                aria-label="Вид списка операций"
                className="inline-flex rounded-lg border border-line bg-bg-surface p-0.5 text-xs"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={importView === 'chronological'}
                  onClick={() => setImportViewPersistent('chronological')}
                  className={
                    'rounded-md px-3 py-1.5 transition '
                    + (importView === 'chronological'
                      ? 'bg-bg-surface2 font-medium text-ink'
                      : 'text-ink-3 hover:text-ink')
                  }
                >
                  По дате
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={importView === 'clusters'}
                  onClick={() => setImportViewPersistent('clusters')}
                  className={
                    'rounded-md px-3 py-1.5 transition '
                    + (importView === 'clusters'
                      ? 'bg-bg-surface2 font-medium text-ink'
                      : 'text-ink-3 hover:text-ink')
                  }
                >
                  Группы
                </button>
              </div>
            </div>
            {importView === 'chronological' ? (
              // Queue mode: cross-session flat list. `sessionId={0}` is a
              // sentinel — TxRow falls back to `row.session_id` for per-row
              // API routing (see TxRow.effectiveSessionId).
              <ChronologicalView
                sessionId={activeSessionId ?? 0}
                preview={preview}
                rows={queue.rows.length > 0 ? queue.rows : undefined}
              />
            ) : activeSessionId !== null ? (
              <>
                <ClusterGrid sessionId={activeSessionId} preview={preview} clusters={clusters} />
                <AttentionFeed sessionId={activeSessionId} preview={preview} clusters={clusters} />
              </>
            ) : (
              // Cluster mode without an active session — temporary
              // limitation while queue-level cluster bulk-apply is a
              // follow-up. Direct user to chronological for now.
              <div className="surface-card p-6 text-center text-sm text-ink-3">
                Группы операций пока показываются по одной выписке. Открой выписку из очереди или используй вид «По дате».
              </div>
            )}
          </>
        )}
      </div>

      <ImportFabCluster
        preview={preview}
        onOpenQueue={openQueueAtPill}
      />

      {queueOpen ? (
        <QueuePanel
          origin={queueOpen}
          onClose={() => setQueueOpen(null)}
          onResume={(id) => setActive(id)}
          onOpenMapping={(id) => setMappingSessionId(id)}
          onOpenCustomCreate={(synthetic) => {
            // «Нет» from inline-prompt → open full create-account form
            // pre-filled from extracted bank/type. QueuePanel synthesizes
            // the upload-shaped payload and hands it off; we keep it open
            // so the user can return to the queue afterwards.
            setCreateAccountState(synthetic);
          }}
          activeSessionId={activeSessionId}
        />
      ) : null}

      {mappingSessionId !== null ? (
        <MappingModal sessionId={mappingSessionId} onClose={() => setMappingSessionId(null)} />
      ) : null}

      {duplicateState && duplicateState.action_required === 'choose' && (
        <DuplicateModal
          open
          action="choose"
          existingSessionId={duplicateState.session_id}
          existingProgress={duplicateState.existing_progress ?? null}
          existingStatus={duplicateState.existing_status ?? null}
          existingCreatedAt={duplicateState.existing_created_at ?? null}
          filename={duplicateState.filename}
          onOpenExisting={handleDuplicateOpenExisting}
          onForceNew={handleDuplicateForceNew}
          onCancel={handleDuplicateCancel}
        />
      )}
      {duplicateState && duplicateState.action_required === 'warn' && (
        <DuplicateModal
          open
          action="warn"
          existingSessionId={duplicateState.session_id}
          existingStatus={duplicateState.existing_status ?? null}
          existingCreatedAt={duplicateState.existing_created_at ?? null}
          filename={duplicateState.filename}
          onForceNew={handleDuplicateForceNew}
          onCancel={handleDuplicateCancel}
        />
      )}
      {unsupportedBank && (
        <BankSupportRequestModal
          bank={unsupportedBank}
          onClose={() => setUnsupportedBank(null)}
        />
      )}

      {/* Auto-account-recognition Шаг 3: 2+ candidates picker. Lets the user
          pick which of their existing matching accounts owns this statement.
          "Create new" routes to the create-account modal below by handing
          off candidatesState into createAccountState. */}
      {candidatesState && (
        <AccountCandidatesPickerModal
          open
          sessionId={candidatesState.session_id}
          bankName={
            candidatesState.account_candidates?.[0]?.bank_name ?? null
          }
          candidates={candidatesState.account_candidates ?? []}
          onClose={() => setCandidatesState(null)}
          onPicked={async () => {
            const sid = candidatesState.session_id;
            setCandidatesState(null);
            await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
            await queryClient.invalidateQueries({ queryKey: ['imports', 'preview', sid] });
            setActive(sid);
          }}
          onCreateNew={() => {
            // Hand off to the create-account modal — the picker closes and
            // the next render shows CreateAccountFromImportModal pre-filled
            // from the same upload payload.
            setCreateAccountState(candidatesState);
            setCandidatesState(null);
          }}
        />
      )}

      {/* Auto-account-recognition Шаг 3+: quick confirm prompt. Replaces the
          immediate full-form modal as the first step. Customize/Other routes
          back into createAccountState to open the full form below. */}
      {confirmState && confirmState.suggested_bank_id && (
        <AccountTypeConfirmModal
          open
          sessionId={confirmState.session_id}
          bankId={confirmState.suggested_bank_id}
          bankNameHint={
            confirmState.account_candidates?.[0]?.bank_name ?? null
          }
          accountTypeHint={confirmState.account_type_hint}
          contractNumber={confirmState.contract_number}
          statementAccountNumber={confirmState.statement_account_number}
          onClose={() => setConfirmState(null)}
          onAttached={async () => {
            const sid = confirmState.session_id;
            setConfirmState(null);
            await queryClient.invalidateQueries({ queryKey: ['imports', 'preview', sid] });
            setActive(sid);
          }}
          onCustomize={() => {
            // Hand off to the full form, preserving the upload payload.
            setCreateAccountState(confirmState);
            setConfirmState(null);
          }}
        />
      )}

      {/* Auto-account-recognition Шаг 3: create-account from import. Opens
          when requires_account_creation=true OR when the candidates picker
          handed off via "Создать новый счёт". */}
      {createAccountState && createAccountState.suggested_bank_id && (
        <CreateAccountFromImportModal
          open
          sessionId={createAccountState.session_id}
          bankId={createAccountState.suggested_bank_id}
          accountTypeHint={createAccountState.account_type_hint}
          contractNumber={createAccountState.contract_number}
          statementAccountNumber={createAccountState.statement_account_number}
          onClose={() => setCreateAccountState(null)}
          onAttached={async () => {
            const sid = createAccountState.session_id;
            setCreateAccountState(null);
            await queryClient.invalidateQueries({ queryKey: ['imports', 'preview', sid] });
            setActive(sid);
          }}
        />
      )}
    </div>
    </FlyToFabProvider>
  );
}

function UnsupportedBankBanner({
  banks,
  onRequestSupport,
}: {
  banks: { id: number; name: string }[];
  onRequestSupport: (bank: { id: number; name: string }) => void;
}) {
  // Soft warning above the import area. The list is short — one row per
  // unsupported bank the user has an account for. Click → opens the same
  // BankSupportRequestModal as the post-error path, pre-filled with the
  // bank id, so the user can jump straight to filing a support request
  // without first attempting (and failing) an upload.
  const heading = banks.length === 1
    ? `Импорт из «${banks[0].name}» пока не поддерживается`
    : 'Несколько твоих банков пока не поддерживают импорт';
  return (
    <div className="mt-3 rounded-md border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p className="font-medium">{heading}</p>
      <p className="mt-1 text-amber-800">
        Загрузка выписки из этих банков будет отклонена. Запроси поддержку — мы добавим формат, когда сможем.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {banks.map((b) => (
          <button
            key={b.id}
            type="button"
            onClick={() => onRequestSupport(b)}
            className="rounded-md border border-amber-400/70 bg-white px-2 py-1 text-xs font-medium text-amber-900 hover:bg-amber-100"
          >
            Запросить поддержку «{b.name}»
          </button>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ hasSupportedAccount }: { hasSupportedAccount: boolean | null }) {
  const [requestOpen, setRequestOpen] = useState(false);

  // hasSupportedAccount === false → user has accounts but none of their banks
  // are in the import whitelist. Don't tell them to "upload a statement" —
  // the upload would be rejected by the backend guard. Surface the gap and
  // route them to the bank-support request flow.
  if (hasSupportedAccount === false) {
    return (
      <>
        <section className="surface-card flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
          <p className="font-serif text-2xl text-ink">Импорт пока не поддерживается ни для одного твоего счёта</p>
          <p className="max-w-md text-sm text-ink-2">
            Сейчас выписки распознаются у Сбера, Т-Банка, Озон Банка и Яндекс Банка. Если работаешь с другим банком —
            напиши нам, какой формат добавить, мы расширим поддержку.
          </p>
          <Button type="button" onClick={() => setRequestOpen(true)} className="mt-2">
            Запросить поддержку банка
          </Button>
        </section>
        {requestOpen && <BankSupportRequestModal onClose={() => setRequestOpen(false)} />}
      </>
    );
  }
  return (
    <section className="surface-card flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      <p className="font-serif text-2xl text-ink">Загрузи первую выписку</p>
      <p className="max-w-md text-sm text-ink-2">
        Поддерживаются CSV, XLSX и PDF из крупных российских банков. После загрузки система автоматически
        распознает структуру, найдёт переводы между счетами и подскажет категории.
      </p>
    </section>
  );
}

/**
 * Map a backend upload error into a user-facing string. The validator emits
 * structured payloads (see `app/services/upload_validator.py:to_payload()`)
 * with a `code` field and per-code extras; surface those numbers when present
 * so the toast says «47 МБ при лимите 25», not generic «too large».
 */
function formatUploadError(err: Error): string {
  if (!(err instanceof ApiError)) {
    return err.message || 'Не удалось загрузить файл';
  }
  const p = err.payload ?? {};
  const code = typeof p.code === 'string' ? p.code : undefined;
  const detail = typeof p.detail === 'string' ? p.detail : err.detail;

  // MUST stay first: 429 rate_limit_exceeded uses a different payload shape
  // (retry_after_seconds, no max_size_mb) than the upload-validator codes
  // below. Reorder and the generic fallback at the bottom will swallow it.
  if (err.status === 429 && code === 'rate_limit_exceeded') {
    return formatRateLimitErrorUpload(p);
  }
  if (code === 'global_body_size_exceeded' || code === 'upload_too_large') {
    const max = typeof p.max_size_mb === 'number' ? p.max_size_mb : undefined;
    const actual = typeof p.actual_size_mb === 'number' ? p.actual_size_mb : undefined;
    if (max !== undefined && actual !== undefined) {
      return `Файл ${actual} МБ превышает лимит ${max} МБ.`;
    }
  }
  if (code === 'xlsx_decompression_too_large') {
    const max = typeof p.max_decompressed_mb === 'number' ? p.max_decompressed_mb : undefined;
    const actual = typeof p.actual_decompressed_mb === 'number' ? p.actual_decompressed_mb : undefined;
    if (max !== undefined && actual !== undefined) {
      return `XLSX распаковывается в ${actual} МБ при лимите ${max} МБ — возможный zip-bomb.`;
    }
  }
  if (code === 'extension_content_mismatch') {
    return 'Содержимое файла не совпадает с расширением.';
  }
  if (code === 'empty_file') {
    return 'Файл пустой.';
  }
  if (code === 'unsupported_upload_type') {
    return 'Формат файла не поддерживается. Загрузи CSV, XLSX или PDF.';
  }
  if (code === 'xlsx_missing_manifest' || code === 'xlsx_invalid_archive') {
    return 'Файл с расширением .xlsx не похож на корректную таблицу Excel.';
  }
  if (code === 'bank_unsupported') {
    // Reached only if onError can't open the modal (missing bank_id).
    // The happy path is intercepted earlier in `uploadMut.onError`.
    const name = typeof p.bank_name === 'string' ? p.bank_name : 'этого банка';
    return `Импорт из «${name}» пока не поддерживается.`;
  }
  return detail || 'Не удалось загрузить файл';
}
