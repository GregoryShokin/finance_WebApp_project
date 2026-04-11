'use client';

import { useMemo } from 'react';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { Account } from '@/types/account';
import type { FinancialHealth } from '@/types/financial-health';
import type { Transaction } from '@/types/transaction';

type Props = {
  accounts: Account[];
  transactions: Transaction[];
  health: FinancialHealth;
  isLoading?: boolean;
};

function toNumber(value: number | string | null | undefined) {
  return Number(value ?? 0);
}

function getDtiColor(dti: number) {
  if (dti < 30) return '#1D9E75';
  if (dti < 40) return '#EF9F27';
  return '#E24B4A';
}

function getLoadBadge(dti: number) {
  if (dti < 30) return { label: 'Кредитная нагрузка в норме', className: 'bg-emerald-100 text-emerald-700' };
  if (dti < 40) return { label: 'Нагрузка допустима', className: 'bg-amber-100 text-amber-700' };
  return { label: 'Высокая нагрузка', className: 'bg-rose-100 text-rose-700' };
}

function getUtilizationTone(percent: number) {
  if (percent < 50) return 'bg-emerald-500';
  if (percent < 80) return 'bg-amber-400';
  return 'bg-rose-500';
}

export function CreditsWidget({ accounts, transactions, health, isLoading = false }: Props) {
  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'credits-widget', expandHeight: 500 });

  const metrics = useMemo(() => {
    const paymentHistoryAccountIds = new Set<number>();
    for (const transaction of transactions) {
      if (transaction.operation_type !== 'credit_payment') continue;
      const accountId = transaction.credit_account_id ?? transaction.target_account_id;
      if (accountId != null) {
        paymentHistoryAccountIds.add(accountId);
      }
    }

    const creditAccounts = accounts.filter((account) => account.account_type === 'credit');
    const creditCards = accounts
      .filter((account) => account.account_type === 'credit_card')
      .map((account) => {
        const limit = toNumber(account.credit_limit_original);
        const used = account.credit_limit_original != null ? Math.max(0, limit - toNumber(account.balance)) : 0;
        const utilization = limit > 0 ? (used / limit) * 100 : 0;
        return {
          ...account,
          limit,
          used,
          utilization,
          hasPaymentHistory: paymentHistoryAccountIds.has(account.id),
        };
      });

    const creditDebt = creditAccounts.reduce((sum, account) => sum + Math.abs(toNumber(account.balance)), 0);
    const creditCardUsed = creditCards.reduce((sum, card) => sum + card.used, 0);

    return {
      creditAccounts,
      creditCards,
      totalDebt: creditDebt + creditCardUsed,
    };
  }, [accounts, transactions]);

  const dtiColor = getDtiColor(health.dti);
  const loadBadge = getLoadBadge(health.dti);

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-medium text-slate-500">Кредиты</p>
          <div className="mt-4 space-y-2">
            <div className="h-9 w-32 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-24 animate-pulse rounded bg-slate-100" />
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-sm font-medium text-slate-500">Кредиты</p>
        {toggleButton}

        {!isExpanded ? (
          <div className="mt-4">
            {metrics.totalDebt > 0 ? (
              <p className="text-2xl font-semibold text-rose-600 lg:text-3xl">{formatMoney(metrics.totalDebt)}</p>
            ) : (
              <p className="text-2xl font-semibold text-slate-400 lg:text-3xl">Кредитов нет</p>
            )}
            <span className={cn('mt-3 inline-flex rounded-full px-2.5 py-1 text-xs font-medium', loadBadge.className)}>
              {loadBadge.label}
            </span>
            <p className="mt-2 text-sm text-slate-500">{health.dti.toFixed(1)}% от дохода</p>
          </div>
        ) : (
          <div className="mt-5 space-y-4">
            {metrics.creditAccounts.length > 0 ? (
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Кредиты</p>
                <div className="mt-3 space-y-3">
                  {metrics.creditAccounts.map((account) => (
                    <div key={account.id} className="rounded-2xl bg-rose-50 px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-sm text-slate-700">{account.name}</span>
                        <span className="font-medium text-rose-600">{formatMoney(Math.abs(toNumber(account.balance)))}</span>
                      </div>
                      {(account.credit_interest_rate != null || account.credit_term_remaining != null) ? (
                        <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400">
                          {account.credit_interest_rate != null ? <span>{toNumber(account.credit_interest_rate)}% годовых</span> : null}
                          {account.credit_term_remaining != null ? <span>осталось {account.credit_term_remaining} мес.</span> : null}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {metrics.creditCards.length > 0 ? (
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Кредитные карты</p>
                <div className="mt-3 space-y-3">
                  {metrics.creditCards.map((card) => (
                    <div key={card.id} className="rounded-2xl bg-slate-50 px-4 py-3">
                      <div className="flex items-center justify-between gap-3 text-sm">
                        <span className="text-slate-700">{card.name}</span>
                        <span className="font-medium text-slate-900">
                          {formatMoney(card.used)} / {formatMoney(card.limit)}
                        </span>
                      </div>
                      <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={cn('h-full rounded-full transition-all duration-500', getUtilizationTone(card.utilization))}
                          style={{ width: `${Math.min(card.utilization, 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <hr className="border-slate-100" />

            <div className="space-y-2 rounded-2xl bg-slate-50 px-4 py-4 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Ежемесячный платёж</span>
                <span className="font-medium text-slate-900">{formatMoney(health.dti_total_payments)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">Кредитная нагрузка</span>
                <span className="font-medium" style={{ color: dtiColor }}>{health.dti.toFixed(1)}% от дохода</span>
              </div>
            </div>

            {health.dti >= 40 ? (
              <div className="rounded-2xl border-l-2 border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                Нагрузка выше нормы — сначала закрой самый дорогой кредит
              </div>
            ) : null}
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
