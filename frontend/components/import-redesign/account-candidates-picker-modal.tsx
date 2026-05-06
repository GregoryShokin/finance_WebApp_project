'use client';

/**
 * Auto-account-recognition Шаг 3 (2026-05-06).
 *
 * When the upload response carries 2+ `account_candidates`, the extractor
 * matched the user's accounts at this bank+type but couldn't pick one
 * automatically (e.g. "Сбер дебет 1" + "Сбер дебет 2"). This modal lets
 * the user pick the right one with one click — much faster than the queue
 * dropdown, and pre-selecting one would risk the wrong default.
 *
 * Also offers a "Create new account" escape hatch for the case where the
 * statement is from yet another account at the same bank that wasn't
 * imported before.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Dialog } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { assignSessionAccount } from '@/lib/api/imports';
import type { ImportAccountCandidate } from '@/types/import';

const TYPE_LABELS: Record<string, string> = {
  main: 'Дебет',
  cash: 'Наличные',
  credit_card: 'Кредитная карта',
  installment_card: 'Карта рассрочки',
  loan: 'Кредит',
  marketplace: 'Маркетплейс',
  broker: 'Брокерский',
  savings: 'Вклад',
  savings_account: 'Накопительный',
  currency: 'Валютный',
};

export function AccountCandidatesPickerModal({
  open,
  sessionId,
  bankName,
  candidates,
  onClose,
  onPicked,
  onCreateNew,
}: {
  open: boolean;
  sessionId: number;
  bankName: string | null;
  candidates: ImportAccountCandidate[];
  onClose: () => void;
  // Called after the chosen account is attached to the session.
  onPicked: () => void;
  // User wants a fresh account at this bank instead of any candidate.
  onCreateNew: () => void;
}) {
  const queryClient = useQueryClient();

  const attachMut = useMutation({
    mutationFn: async (accountId: number) => {
      await assignSessionAccount(sessionId, accountId);
      return accountId;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['import-sessions'] });
      toast.success('Счёт привязан к выписке');
      onPicked();
    },
    onError: (e: Error) => toast.error(e.message || 'Не удалось привязать счёт'),
  });

  const heading = bankName
    ? `Несколько твоих счетов «${bankName}» подходят к этой выписке`
    : 'Несколько счетов подходят к этой выписке';

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Выбери счёт"
      description={heading}
    >
      <div className="space-y-2">
        {candidates.map((c) => {
          const typeLabel = TYPE_LABELS[c.account_type] ?? c.account_type;
          return (
            <button
              key={c.id}
              type="button"
              disabled={attachMut.isPending}
              onClick={() => attachMut.mutate(c.id)}
              className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-900">
                  {c.name}
                  {c.is_closed ? <span className="ml-2 text-xs text-slate-500">(закрыт)</span> : null}
                </p>
                <p className="truncate text-xs text-slate-500">
                  {typeLabel}
                  {c.contract_number ? ` · договор ${c.contract_number}` : null}
                  {c.statement_account_number ? ` · ${c.statement_account_number}` : null}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-between">
        <Button type="button" variant="ghost" onClick={onCreateNew} disabled={attachMut.isPending}>
          Создать новый счёт
        </Button>
        <Button type="button" variant="ghost" onClick={onClose} disabled={attachMut.isPending}>
          Отмена
        </Button>
      </div>
    </Dialog>
  );
}
