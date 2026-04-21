'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, FileText, SquareArrowUp, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { Account } from '@/types/account';
import { getAccounts } from '@/lib/api/accounts';
import { assignSessionAccount, deleteImportSession, getImportSessions } from '@/lib/api/imports';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import {
  dequeueImportSession,
  getQueuedImportSessions,
  IMPORT_QUEUE_EVENT,
} from '@/lib/utils/import-queue';

function AccountSelector({
  sessionId,
  currentAccountId,
  accounts,
  onAssigned,
}: {
  sessionId: number;
  currentAccountId: number | null;
  accounts: Account[];
  onAssigned: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({});
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const assignMutation = useMutation({
    mutationFn: (accountId: number) => assignSessionAccount(sessionId, accountId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Счёт привязан — переводы пересопоставлены');
      setOpen(false);
      onAssigned();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось привязать счёт'),
  });

  function handleOpen() {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    setDropdownStyle({
      position: 'fixed',
      top: rect.bottom + 4,
      left: rect.left,
      minWidth: rect.width,
      width: 224,
      zIndex: 9999,
    });
    setOpen((v) => !v);
  }

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      const target = e.target as Node;
      if (
        buttonRef.current && !buttonRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [open]);

  const currentName = accounts.find((a) => a.id === currentAccountId)?.name ?? 'Счёт не распознан';
  const isUnknown = !currentAccountId;

  const dropdown = open && (
    <div
      ref={dropdownRef}
      style={dropdownStyle}
      className="rounded-2xl border border-slate-200 bg-white py-1 shadow-xl"
    >
      {accounts.map((account) => (
        <button
          key={account.id}
          type="button"
          disabled={assignMutation.isPending}
          onClick={() => assignMutation.mutate(account.id)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          <span className="truncate">{account.name}</span>
          {account.id === currentAccountId && (
            <span className="ml-auto text-xs text-slate-400">✓</span>
          )}
        </button>
      ))}
    </div>
  );

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={handleOpen}
        className={[
          'inline-flex max-w-full items-center gap-2 rounded-2xl px-3 py-1.5 transition',
          isUnknown ? 'bg-amber-50 hover:bg-amber-100' : 'bg-slate-50 hover:bg-slate-100',
        ].join(' ')}
        title="Изменить счёт"
      >
        <p className={`text-[11px] font-medium uppercase tracking-[0.12em] ${isUnknown ? 'text-amber-500' : 'text-slate-400'}`}>
          Счёт
        </p>
        <p className={`truncate text-sm font-medium ${isUnknown ? 'text-amber-700' : 'text-slate-700'}`}>
          {currentName}
        </p>
        <ChevronDown className={`size-3 shrink-0 ${isUnknown ? 'text-amber-400' : 'text-slate-400'}`} />
      </button>
      {typeof document !== 'undefined' && dropdown && createPortal(dropdown, document.body)}
    </>
  );
}

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

  const sessions = useMemo(() => {
    return sessionsQuery.data?.sessions ?? [];
  }, [sessionsQuery.data?.sessions]);

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

                <AccountSelector
                  sessionId={session.id}
                  currentAccountId={session.account_id ?? null}
                  accounts={accountsQuery.data ?? []}
                  onAssigned={() => {}}
                />
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
