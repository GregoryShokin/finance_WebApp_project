'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { Account } from '@/types/account';
import type { Counterparty } from '@/types/counterparty';
import type { GoalWithProgress } from '@/types/goal';
import type { Transaction } from '@/types/transaction';

import { getFreeNetCapitalMetrics } from '@/components/dashboard/free-net-capital-data';


type Props = {
  accounts: Account[];
  goals: GoalWithProgress[];
  counterparties: Counterparty[];
  transactions: Transaction[];
  isLoading?: boolean;
};

function formatYAxisValue(value: number) {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}м`;
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}к`;
  return String(Math.round(value));
}

export function FreeNetCapitalWidget({
  accounts,
  goals,
  counterparties,
  transactions,
  isLoading = false,
}: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const metrics = useMemo(
    () => getFreeNetCapitalMetrics(accounts, goals, counterparties, transactions),
    [accounts, goals, counterparties, transactions],
  );

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, isLoading, metrics]);

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
      if (customEvent.detail?.source !== 'free-net-capital-widget' && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, []);

  function handleToggle() {
    setIsExpanded((current) => {
      const next = !current;
      document.dispatchEvent(
        new CustomEvent(FI_SCORE_WIDGET_EVENT, {
          detail: { source: 'free-net-capital-widget', open: next },
        }),
      );
      return next;
    });
  }

  function renderDelta() {
    if (!metrics || metrics.deltaFromPreviousMonth === null) {
      return <p className="mt-3 text-sm text-slate-400">Недостаточно данных для сравнения</p>;
    }

    const delta = metrics.deltaFromPreviousMonth;
    const isPositive = delta > 0;
    const isNegative = delta < 0;

    return (
      <p className={cn('mt-3 text-sm font-medium', isPositive ? 'text-emerald-600' : isNegative ? 'text-rose-600' : 'text-slate-500')}>
        {isPositive ? '+' : isNegative ? '−' : ''}
        {formatMoney(Math.abs(delta))} за месяц
      </p>
    );
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-medium text-slate-500">Свободный чистый капитал</p>
          <p className="mt-1 text-sm text-slate-500">Свободные активы за вычетом долгов</p>
          <div className="mt-4 space-y-2">
            <div className="h-9 w-40 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-32 animate-pulse rounded bg-slate-100" />
          </div>
        </>
      );
    }

    if (!metrics) {
      return (
        <>
          <div className="flex items-start justify-between gap-4">
            <div className="pr-4">
              <p className="text-sm font-medium text-slate-500">Свободный чистый капитал</p>
              <p className="mt-1 text-sm text-slate-500">Свободные активы за вычетом долгов</p>
            </div>
            <button
              type="button"
              onClick={handleToggle}
              className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
              aria-label="Подробнее"
              aria-expanded={isExpanded}
            >
              i
            </button>
          </div>
          <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
            Недостаточно данных
          </div>
        </>
      );
    }

    return (
      <>
        <div className="flex items-start justify-between gap-4">
          <div className="pr-4">
            <p className="text-sm font-medium text-slate-500">Свободный чистый капитал</p>
            <p className="mt-1 text-sm text-slate-500">Свободные активы за вычетом долгов</p>
          </div>
          <button
            type="button"
            onClick={handleToggle}
            className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
            aria-label="Подробнее"
            aria-expanded={isExpanded}
          >
            i
          </button>
        </div>

        {!isExpanded ? (
          <>
            <div className="mt-4">
              <MoneyAmount
                value={metrics.freeNetCapital}
                tone={metrics.freeNetCapital >= 0 ? 'income' : 'expense'}
                className="text-2xl lg:text-3xl"
              />
              {renderDelta()}
            </div>
          </>
        ) : (
          <>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Личные активы</p>
                <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.personalAssets)}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Целевые активы</p>
                <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.targetAssets)}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Долги</p>
                <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.debts)}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Свободный чистый капитал</p>
                <p className={cn('mt-1 font-medium', metrics.freeNetCapital >= 0 ? 'text-slate-900' : 'text-rose-600')}>
                  {formatMoney(metrics.freeNetCapital)}
                </p>
              </div>
            </div>

            <div className="mt-5 h-[260px] rounded-[28px] bg-slate-50/70 px-3 py-4 sm:px-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={metrics.chartData} barCategoryGap="28%">
                  <CartesianGrid vertical={false} stroke="#E2E8F0" strokeDasharray="3 3" />
                  <XAxis dataKey="month" tickLine={false} axisLine={false} tick={{ fill: '#64748B', fontSize: 12 }} />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: '#94A3B8', fontSize: 12 }}
                    tickFormatter={formatYAxisValue}
                    width={52}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                    formatter={(value: number) => [formatMoney(value), 'Свободный чистый капитал']}
                    labelFormatter={(label) => `Месяц: ${label}`}
                  />
                  <Bar dataKey="value" fill="#0F172A" radius={[10, 10, 0, 0]} maxBarSize={44} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-4 space-y-2 text-sm text-slate-600">
              {metrics.messageLines.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          </>
        )}
      </>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative self-start overflow-visible"
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
          className={cn(
            'relative overflow-visible transition-[width,transform,box-shadow] duration-300 ease-out p-5',
            isExpanded
              ? 'absolute inset-x-0 top-0 z-50 shadow-2xl lg:p-6 xl:w-[calc(154%+1rem)] xl:max-w-[calc(154%+1rem)]'
              : 'w-full',
          )}
          style={{
            transformOrigin: 'left top',
            transform: isExpanded ? 'translateY(-4px)' : 'translateY(0)',
          }}
        >
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}
