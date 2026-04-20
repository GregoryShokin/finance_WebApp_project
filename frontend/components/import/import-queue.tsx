'use client';

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, SquareArrowUp, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { getAccounts } from '@/lib/api/accounts';
import { deleteImportSession, getImportSessions } from '@/lib/api/imports';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import {
  dequeueImportSession,
  getQueuedImportSessions,
  IMPORT_QUEUE_EVENT,
} from '@/lib/utils/import-queue';

export function ImportQueue({ onResume }: { onResume: (id: number) => void }) {
  const queryClient = useQueryClient();
  const [resumingId, setResumingId] = useState<number | null>(null);
  const sessionsQuery = useQuery({
    queryKey: ['import-sessions'],
    queryFn: getImportSessions,
  });
  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
  });
  const [queuedIds, setQueuedIds] = useState<number[]>([]);

  useEffect(() => {
    function syncQueue() {
      setQueuedIds(getQueuedImportSessions().map((entry) => entry.id));
    }

    syncQueue();
    window.addEventListener(IMPORT_QUEUE_EVENT, syncQueue as EventListener);
    window.addEventListener('storage', syncQueue);
    return () => {
      window.removeEventListener(IMPORT_QUEUE_EVENT, syncQueue as EventListener);
      window.removeEventListener('storage', syncQueue);
    };
  }, []);

  const deleteMutation = useMutation({
    mutationFn: deleteImportSession,
    onSuccess: async (_, sessionId) => {
      dequeueImportSession(sessionId);
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Выписка удалена из очереди');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось удалить выписку');
    },
  });

  const queuedEntries = useMemo(() => getQueuedImportSessions(), [queuedIds]);

  const sessions = useMemo(() => {
    return sessionsQuery.data?.sessions ?? [];
  }, [sessionsQuery.data?.sessions]);

  const accountNames = useMemo(
    () => new Map((accountsQuery.data ?? []).map((account) => [String(account.id), account.name])),
    [accountsQuery.data],
  );

  if (sessionsQuery.isLoading) {
    return <LoadingState title="Загружаем очередь..." description="Собираем отложенные выписки." />;
  }

  if (sessionsQuery.isError) {
    return <ErrorState title="Не удалось загрузить очередь" description="Повтори попытку чуть позже." />;
  }

  if (sessions.length === 0) {
    return <EmptyState title="Очередь пуста" description="Загрузи выписку вручную или через Telegram-бота — она появится здесь." />;
  }

  return (
    <div className="space-y-3">
      {sessions.map((session) => {
        const queuedEntry = queuedEntries.find((entry) => entry.id === session.id);
        const accountName =
          accountNames.get(String(session.account_id ?? '')) ??
          accountNames.get(String(queuedEntry?.accountId ?? '')) ??
          'Счёт не распознан';

        return (
          <Card
            key={session.id}
            className="rounded-[28px] border border-slate-200 bg-white/95 px-3.5 py-3 shadow-soft"
          >
            <div className="flex items-center gap-3">
              <div className="flex size-9 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-500">
                <FileText className="size-4.5" />
              </div>

              <div className="min-w-0 flex-1 space-y-2">
                <p className="truncate text-sm font-semibold text-slate-900">
                  {session.filename}
                </p>

                <div className="inline-flex max-w-full items-center gap-2 rounded-2xl bg-slate-50 px-3 py-1.5">
                  <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-slate-400">
                    Счёт
                  </p>
                  <p className="truncate text-sm font-medium text-slate-700">
                    {accountName}
                  </p>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  disabled={resumingId === session.id}
                  onClick={() => {
                    setResumingId(session.id);
                    onResume(session.id);
                  }}
                  className="inline-flex size-8 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
                  aria-label="Продолжить выписку"
                  title="Продолжить выписку"
                >
                  <SquareArrowUp className="size-4" />
                </button>
                <button
                  type="button"
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(session.id)}
                  className="inline-flex size-8 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 shadow-sm transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-60"
                  aria-label="Удалить выписку"
                  title="Удалить выписку"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
