'use client';

import { useMemo } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { deleteCounterparty } from '@/lib/api/counterparties';
import { formatMoney } from '@/lib/utils/format';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { Counterparty } from '@/types/counterparty';
import type { FinancialHealth } from '@/types/financial-health';

type Props = {
  counterparties: Counterparty[];
  health: FinancialHealth;
  isLoading?: boolean;
};

export function DebtsWidget({ counterparties, health: _health, isLoading = false }: Props) {
  const queryClient = useQueryClient();

  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'debts-widget', expandHeight: 500 });

  const metrics = useMemo(() => {
    const totalReceivable = counterparties.reduce((sum, item) => sum + Number(item.receivable_amount), 0);
    const totalPayable = counterparties.reduce((sum, item) => sum + Number(item.payable_amount), 0);
    const netBalance = totalReceivable - totalPayable;
    const receivables = counterparties.filter((item) => Number(item.receivable_amount) > 0);
    const payables = counterparties.filter((item) => Number(item.payable_amount) > 0);
    const hasAnyDebt = counterparties.some(
      (item) => Number(item.receivable_amount) > 0 || Number(item.payable_amount) > 0,
    );

    return {
      totalReceivable,
      totalPayable,
      netBalance,
      receivables,
      payables,
      hasAnyDebt,
    };
  }, [counterparties]);

  async function handleDelete(counterparty: Counterparty) {
    const confirmed = window.confirm(`Удалить "${counterparty.name}" вместе с историей долга?`);
    if (!confirmed) return;

    try {
      await deleteCounterparty(counterparty.id);
      await queryClient.invalidateQueries({ queryKey: ['counterparties'] });
      toast.success(`${counterparty.name} удалён`);
    } catch {
      toast.error('Не удалось удалить');
    }
  }

  function renderCounterpartyRow(counterparty: Counterparty, amount: number, toneClass: string) {
    return (
      <div
        key={counterparty.id}
        className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-4 py-3"
      >
        <span className="truncate text-sm text-slate-700">{counterparty.name}</span>
        <div className="flex items-center gap-3">
          <span className={cn('text-sm font-medium', toneClass)}>{formatMoney(amount)}</span>
          <button
            type="button"
            onClick={() => handleDelete(counterparty)}
            className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-rose-600"
            aria-label={`Удалить ${counterparty.name}`}
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>
    );
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-medium text-slate-500">Долги</p>
          <div className="mt-4 space-y-2">
            <div className="h-5 w-40 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-40 animate-pulse rounded bg-slate-100" />
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-sm font-medium text-slate-500">Долги</p>
        {metrics.hasAnyDebt ? toggleButton : null}

        {!metrics.hasAnyDebt ? (
          <p className="mt-4 text-sm text-slate-400">Долгов нет</p>
        ) : !isExpanded ? (
          <div className="mt-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-slate-500">Мне должны</span>
              <span className={cn('text-sm font-medium', metrics.totalReceivable > 0 ? 'text-emerald-600' : 'text-slate-400')}>
                {metrics.totalReceivable > 0 ? formatMoney(metrics.totalReceivable) : '0 ₽'}
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-slate-500">Я должен</span>
              <span className={cn('text-sm font-medium', metrics.totalPayable > 0 ? 'text-rose-600' : 'text-slate-400')}>
                {metrics.totalPayable > 0 ? formatMoney(metrics.totalPayable) : '0 ₽'}
              </span>
            </div>
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            {metrics.receivables.length > 0 ? (
              <div className="space-y-3">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Мне должны</p>
                {metrics.receivables.map((counterparty) =>
                  renderCounterpartyRow(counterparty, Number(counterparty.receivable_amount), 'text-emerald-600'),
                )}
              </div>
            ) : null}

            {metrics.receivables.length > 0 && metrics.payables.length > 0 ? <hr className="border-slate-100" /> : null}

            {metrics.payables.length > 0 ? (
              <div className="space-y-3">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Я должен</p>
                {metrics.payables.map((counterparty) =>
                  renderCounterpartyRow(counterparty, Number(counterparty.payable_amount), 'text-rose-600'),
                )}
              </div>
            ) : null}

            <div className="rounded-2xl bg-slate-50 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-500">Чистая позиция</span>
                <span
                  className={cn(
                    'text-sm font-medium',
                    metrics.netBalance > 0 ? 'text-emerald-600' : metrics.netBalance < 0 ? 'text-rose-600' : 'text-slate-500',
                  )}
                >
                  {formatMoney(metrics.netBalance)}
                </span>
              </div>
            </div>
          </div>
        )}
      </>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative h-full overflow-visible"
      style={wrapperStyle}
    >
      {backdrop}
      <div ref={cardRef}>
        <Card className="relative overflow-visible p-5" style={cardStyle}>
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}
