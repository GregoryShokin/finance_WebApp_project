'use client';

/**
 * useImportQueue — single source of truth for the unified moderator (v1.23).
 *
 * Hides the per-session abstraction from the UI: the user sees one queue of
 * preview-ready rows aggregated from EVERY active session of theirs, with
 * brand and counterparty groups spanning sessions.
 *
 * Returns:
 *   • sessions   — per-session metadata (bank/account/filename) for source pills
 *   • rows       — flat list of rows enriched with session_id + bank_code + account_id
 *   • clusters   — cross-session bulk clusters (fingerprint / brand / counterparty)
 *   • summary    — aggregated row counters
 *   • refetch    — manual refetch hook (commit / brand-confirm / etc. invalidate
 *                  via React Query keys, no need to call this in 99% of cases)
 *
 * The hook does NOT poll auto_preview status — that's `useActiveImportSession`'s
 * job (used by QueuePanel for the upload pipeline). The queue itself only
 * shows rows from sessions that have already crossed the preview-ready boundary.
 */

import { useQuery } from '@tanstack/react-query';

import {
  getImportQueueBulkClusters,
  getImportQueuePreview,
} from '@/lib/api/imports';
import type {
  ImportQueueBulkClustersResponse,
  ImportQueuePreviewResponse,
} from '@/types/import';

export function useImportQueue() {
  const previewQuery = useQuery({
    queryKey: ['imports', 'queue', 'preview'],
    queryFn: getImportQueuePreview,
    // Re-fetch on window focus so the user can flip between tabs (upload
    // a statement in another tab, come back here, see new rows).
    refetchOnWindowFocus: true,
    // Stable cache — invalidated by commit / row-confirm / brand-confirm
    // mutations through the same key family.
    staleTime: 0,
  });

  const clustersQuery = useQuery({
    queryKey: ['imports', 'queue', 'bulk-clusters'],
    queryFn: getImportQueueBulkClusters,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });

  return {
    sessions: previewQuery.data?.sessions ?? [],
    rows: previewQuery.data?.rows ?? [],
    summary: previewQuery.data?.summary ?? null,
    clusters: clustersQuery.data ?? null,

    isLoadingPreview: previewQuery.isLoading,
    isLoadingClusters: clustersQuery.isLoading,
    previewError: previewQuery.error as Error | null,
    clustersError: clustersQuery.error as Error | null,

    refetch: () => {
      previewQuery.refetch();
      clustersQuery.refetch();
    },
  } as {
    sessions: ImportQueuePreviewResponse['sessions'];
    rows: ImportQueuePreviewResponse['rows'];
    summary: ImportQueuePreviewResponse['summary'] | null;
    clusters: ImportQueueBulkClustersResponse | null;
    isLoadingPreview: boolean;
    isLoadingClusters: boolean;
    previewError: Error | null;
    clustersError: Error | null;
    refetch: () => void;
  };
}
