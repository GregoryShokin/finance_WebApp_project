'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Info } from 'lucide-react';

import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { Account } from '@/types/account';
import type { FinancialHealth } from '@/types/financial-health';

const SCALE = 1.8;

type Props = {
  accounts: Account[];
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

function getDtiBadge(dti: number) {
  if (dti < 30) return { label: 'Нагрузка в норме', className: 'bg-emerald-100 text-emerald-700' };
  if (dti < 40) return { label: 'Допустимо', className: 'bg-amber-100 text-amber-700' };
  return { label: 'Высокая нагрузка', className: 'bg-rose-100 text-rose-700' };
}

function getUtilizationTone(percent: number) {
  if (percent < 50) return 'bg-emerald-500';
  if (percent < 80) return 'bg-amber-400';
  return 'bg-rose-500';
}

export function CreditsWidget({ accounts, health, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, accounts, health, isLoading]);

  useEffect(() => {
    if (!isExpanded) return;

    function handleClick(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    }

    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded]);

  useEffect(() => {
    function handleExternalToggle(event: Event) {
      const customEvent = event as CustomEvent<{ source?: string; open?: boolean }>;
      if (customEvent.detail?.source !== 'credits-widget' && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, []);

  const metrics = useMemo(() => {
    const creditAccounts = accounts.filter((account) => account.account_type === 'credit');
    const creditCardAccounts = accounts.filter((account) => account.account_type === 'credit_card');

    const creditDebt = creditAccounts.reduce((sum, account) => sum + Math.abs(toNumber(account.balance)), 0);
    const cardItems = creditCardAccounts.map((account) => {
      const limit = toNumber(account.credit_limit_original);
      const used = account.credit_limit_original != null ? Math.max(0, limit - toNumber(account.balance)) : 0;
      const utilization = limit > 0 ? (used / limit) * 100 : 0;

      return {
        ...account,
        limit,
        used,
        utilization,
      };
    });
    const creditCardUsed = cardItems.reduce((sum, card) => sum + card.used, 0);
    const totalDebt = creditDebt + creditCardUsed;

    return {
      creditAccounts,
      creditCards: cardItems,
      creditDebt,
      creditCardUsed,
      totalDebt,
    };
  }, [accounts]);

  const dtiColor = getDtiColor(health.dti);
  const dtiBadge = getDtiBadge(health.dti);

  function handleToggle() {
    setIsExpanded((current) => {
      const next = !current;
      document.dispatchEvent(
        new CustomEvent(FI_SCORE_WIDGET_EVENT, {
          detail: { source: 'credits-widget', open: next },
        }),
      );
      return next;
    });
  }

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
        <div className="flex items-start justify-between gap-4">
          <div className="pr-4">
            <p className="text-sm font-medium text-slate-500">Кредиты</p>
          </div>
          <button
            type="button"
            onClick={handleToggle}
            className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
            aria-label="Подробнее"
            aria-expanded={isExpanded}
          >
            <Info className="size-3.5" />
          </button>
        </div>

        {!isExpanded ? (
          <div className="mt-4">
            {metrics.totalDebt > 0 ? (
              <p className="text-2xl font-semibold text-rose-600 lg:text-3xl">{formatMoney(metrics.totalDebt)}</p>
            ) : (
              <p className="text-2xl font-semibold text-slate-400 lg:text-3xl">Кредитов нет</p>
            )}
            <span className={cn('mt-3 inline-flex rounded-full px-2.5 py-1 text-xs font-medium', dtiBadge.className)}>
              {dtiBadge.label}
            </span>
            <p className="mt-2 text-sm text-slate-500">{health.dti.toFixed(1)}% от дохода</p>
          </div>
        ) : (
          <>
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
                        <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-400">
                          {account.credit_interest_rate != null ? <span>{toNumber(account.credit_interest_rate)}% годовых</span> : null}
                          {account.credit_term_remaining != null ? <span>осталось {account.credit_term_remaining} мес.</span> : null}
                        </div>
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
                          <span className="font-medium text-slate-900">{formatMoney(card.used)}</span>
                        </div>
                        <div className="mt-1 flex items-center justify-between gap-3 text-xs text-slate-400">
                          <span>Лимит: {formatMoney(card.limit)}</span>
                          <span>{card.utilization.toFixed(0)}%</span>
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
                  <span className="text-slate-500">DTI</span>
                  <span className="font-medium" style={{ color: dtiColor }}>{health.dti.toFixed(1)}%</span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-500">Средний доход</span>
                  <span className="font-medium text-slate-900">{formatMoney(health.dti_income)}</span>
                </div>
              </div>

              {health.dti >= 40 ? (
                <div className="rounded-2xl border-l-2 border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                  Нагрузка выше нормы. Приоритет — погасить кредит с наибольшей ставкой.
                </div>
              ) : null}
            </div>
          </>
        )}
      </>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative h-full overflow-visible"
      style={{ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }}
    >
      {isExpanded ? (
        <button
          type="button"
          aria-label="Закрыть"
          onClick={handleToggle}
          className="fixed inset-0 z-40 bg-black/10"
        />
      ) : null}

      <div ref={cardRef}>
        <Card
          className="relative overflow-visible p-5"
          style={{
            position: isExpanded ? 'absolute' : 'relative',
            top: 0,
            left: 0,
            right: 0,
            transform: isExpanded ? `scale(${SCALE})` : 'scale(1)',
            transformOrigin: 'center center',
            transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)',
            zIndex: isExpanded ? 50 : 1,
            overflow: 'visible',
          }}
        >
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}

