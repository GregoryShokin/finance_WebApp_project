'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getImportSessions, getImportPreview, getModerationStatus, getBulkClusters } from '@/lib/api/imports';
import type {
  BulkClustersResponse,
  ImportPreviewResponse,
  ImportSessionListItem,
  ModerationStatusResponse,
} from '@/types/import';

const ACTIVE_KEY = 'financeapp.import.active-session-id.v1';

/**
 * Picks one "current" import session and exposes preview + clusters + moderation
 * for it. Selection rules (in order):
 *   1. Last user-resumed id (set via setActive() and stored in localStorage).
 *   2. Most recent session whose status is past 'preview_ready' but not committed.
 *   3. First session in the list (oldest non-committed).
 *
 * Returns null sessionId if there are no sessions at all (empty inbox).
 */
export function useActiveImportSession() {
  const [explicitId, setExplicitId] = useState<number | null>(null);

  // Restore last-active id from localStorage on mount.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const stored = window.localStorage.getItem(ACTIVE_KEY);
    if (!stored) return;
    const parsed = Number.parseInt(stored, 10);
    if (Number.isFinite(parsed)) setExplicitId(parsed);
  }, []);

  function setActive(id: number | null) {
    setExplicitId(id);
    if (typeof window === 'undefined') return;
    if (id === null) window.localStorage.removeItem(ACTIVE_KEY);
    else window.localStorage.setItem(ACTIVE_KEY, String(id));
  }

  const sessionsQuery = useQuery({
    queryKey: ['import-sessions'],
    queryFn: getImportSessions,
    refetchInterval: (query) => {
      const data = query.state.data as { sessions?: ImportSessionListItem[] } | undefined;
      const inflight = (data?.sessions ?? []).some(
        (s) =>
          s.auto_preview_status === 'pending' ||
          s.auto_preview_status === 'running' ||
          s.transfer_match_status === 'pending' ||
          s.transfer_match_status === 'running',
      );
      return inflight ? 2000 : false;
    },
  });

  const sessions = sessionsQuery.data?.sessions ?? [];

  const activeSessionId = useMemo<number | null>(() => {
    if (explicitId && sessions.some((s) => s.id === explicitId)) return explicitId;

    // Prefer sessions whose moderator is ready (preview built) but not committed.
    const ready = sessions
      .filter((s) => s.status !== 'committed' && (s.auto_preview_status === 'ready' || s.status === 'preview_ready'))
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
    if (ready[0]) return ready[0].id;

    const inProgress = sessions.find((s) => s.status !== 'committed');
    return inProgress ? inProgress.id : null;
  }, [sessions, explicitId]);

  const activeSession = useMemo<ImportSessionListItem | null>(
    () => (activeSessionId ? sessions.find((s) => s.id === activeSessionId) ?? null : null),
    [sessions, activeSessionId],
  );

  const previewQuery = useQuery({
    queryKey: ['imports', 'preview', activeSessionId],
    queryFn: () => getImportPreview(activeSessionId as number),
    enabled: activeSessionId !== null,
  });

  const clustersQuery = useQuery({
    queryKey: ['imports', 'bulk-clusters', activeSessionId],
    queryFn: () => getBulkClusters(activeSessionId as number),
    enabled: activeSessionId !== null,
  });

  const moderationQuery = useQuery({
    queryKey: ['imports', 'moderation-status', activeSessionId],
    queryFn: () => getModerationStatus(activeSessionId as number),
    enabled: activeSessionId !== null,
  });

  return {
    sessions,
    isLoadingSessions: sessionsQuery.isLoading,
    sessionsError: sessionsQuery.error as Error | null,

    activeSessionId,
    activeSession,
    setActive,

    preview: previewQuery.data ?? null,
    isLoadingPreview: previewQuery.isLoading,

    clusters: clustersQuery.data ?? null,
    isLoadingClusters: clustersQuery.isLoading,

    moderation: moderationQuery.data ?? null,
  } as {
    sessions: ImportSessionListItem[];
    isLoadingSessions: boolean;
    sessionsError: Error | null;
    activeSessionId: number | null;
    activeSession: ImportSessionListItem | null;
    setActive: (id: number | null) => void;
    preview: ImportPreviewResponse | null;
    isLoadingPreview: boolean;
    clusters: BulkClustersResponse | null;
    isLoadingClusters: boolean;
    moderation: ModerationStatusResponse | null;
  };
}
