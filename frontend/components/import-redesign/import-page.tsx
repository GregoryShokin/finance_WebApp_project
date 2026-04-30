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

import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { useAuth } from '@/hooks/use-auth';
import {
  commitImport,
  unexcludeImportRow,
  unparkImportRow,
  uploadImportFile,
} from '@/lib/api/imports';

import { ImportActionsBar } from './import-actions-bar';
import { ImportStatusCard } from './import-status-card';
import { ClusterGrid } from './cluster-grid';
import { AttentionFeed } from './attention-feed';
import { ImportFabCluster } from './import-fab-cluster';
import { QueuePanel } from './queue-panel';
import { MappingModal } from './mapping-modal';
import { useActiveImportSession } from './use-active-session';
import { fmtRubAbs } from './format';

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

  const queuePillRef = useRef<HTMLButtonElement | null>(null);
  const [queueOpen, setQueueOpen] = useState<{ x: number; y: number } | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<number | null>(null);

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadImportFile({ file, delimiter: ',' }),
    onSuccess: async (res) => {
      toast.success(`Загружено: ${res.filename}`);
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      setActive(res.session_id);
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось загрузить файл'),
  });

  const commitMut = useMutation({
    mutationFn: (sessionId: number) => commitImport(sessionId, true),
    onSuccess: async (res) => {
      toast.success(`Импортировано: ${res.imported_count} операций`);
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      await queryClient.invalidateQueries({ queryKey: ['imports', 'preview', res.session_id] });
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
  const reviewRows =
    totalRows - readyRows - (preview?.summary.duplicate_rows ?? 0) - (preview?.summary.skipped_rows ?? 0);

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
    <div className="relative flex-1 pb-32">
      <ImportActionsBar
        queuePillRef={queuePillRef}
        uploading={uploadMut.isPending}
        committing={commitMut.isPending}
        resetting={resetMut.isPending}
        resetEnabled={activeSessionId !== null && !!preview}
        onUpload={(file) => uploadMut.mutate(file)}
        onOpenQueue={openQueueAtPill}
        onCommit={() => activeSessionId && commitMut.mutate(activeSessionId)}
        onReset={() => {
          if (!confirm('Сбросить сессию: вернуть все отложенные и исключённые строки обратно в обработку?')) return;
          resetMut.mutate();
        }}
        queueCount={sessions.length}
        queueOk={queueOk}
        queueSnz={queueSnz}
        queueExc={queueExc}
        readyCount={readyRows}
        readySum={readySum}
      />

      <div className="mt-5 space-y-3.5">
        {activeSessionId === null ? (
          <EmptyState />
        ) : isLoadingPreview && !preview ? (
          <div className="surface-card grid h-48 place-items-center text-xs text-ink-3">
            <Loader2 className="size-4 animate-spin" />
          </div>
        ) : (
          <>
            <ImportStatusCard
              totalRows={totalRows}
              readyRows={readyRows}
              reviewRows={Math.max(reviewRows, 0)}
            />
            <ClusterGrid sessionId={activeSessionId} preview={preview} clusters={clusters} />
            <AttentionFeed sessionId={activeSessionId} preview={preview} clusters={clusters} />
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
        />
      ) : null}

      {mappingSessionId !== null ? (
        <MappingModal sessionId={mappingSessionId} onClose={() => setMappingSessionId(null)} />
      ) : null}
    </div>
  );
}

function EmptyState() {
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
