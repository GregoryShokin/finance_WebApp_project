'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { getSafetyBufferMetrics } from '@/components/dashboard/safety-buffer-data';
import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { GoalWithProgress } from '@/types/goal';

type Props = {
  goals: GoalWithProgress[];
  isLoading?: boolean;
};

function formatProgress(value: number) {
  return `${Math.max(0, Math.round(value))}%`;
}

function formatCoverageMonths(value: number) {
  if (!Number.isFinite(value)) {
    return '0.0';
  }

  return value.toFixed(1);
}

export function SafetyBufferWidget({ goals, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const metrics = useMemo(() => getSafetyBufferMetrics(goals), [goals]);

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
      if (customEvent.detail?.source !== 'safety-buffer-widget' && customEvent.detail?.open) {
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
          detail: { source: 'safety-buffer-widget', open: next },
        }),
      );
      return next;
    });
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-medium text-slate-500">Подушка безопасности</p>
          <div className="mt-4 space-y-2">
            <div className="h-9 w-40 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-36 animate-pulse rounded bg-slate-100" />
          </div>
        </>
      );
    }

    if (!metrics) {
      return (
        <>
          <div className="flex items-start justify-between gap-4">
            <div className="pr-4">
              <p className="text-sm font-medium text-slate-500">Подушка безопасности</p>
              <p className="mt-1 text-sm text-slate-500">Накопления в системной цели</p>
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

    const progressWidth = Math.max(0, Math.min(metrics.progressPercent, 100));

    return (
      <>
        <div className="flex items-start justify-between gap-4">
          <div className="pr-4">
            <p className="text-sm font-medium text-slate-500">Подушка безопасности</p>
            <p className="mt-1 text-sm text-slate-500">Накопления в системной цели</p>
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
          <div className="mt-4">
            <MoneyAmount value={metrics.savedAmount} tone="income" className="text-2xl lg:text-3xl" />
            <p className="mt-3 text-sm text-slate-500">{formatProgress(metrics.progressPercent)} от целевого уровня</p>
          </div>
        ) : (
          <>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Накоплено</p>
                <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.savedAmount)}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Цель</p>
                <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.targetAmount)}</p>
              </div>
              <div className="rounded-2xl bg-slate-50 px-4 py-3">
                <p className="text-xs uppercase tracking-wide text-slate-400">Среднемесячные расходы</p>
                <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.avgMonthlyExpenses)}</p>
              </div>
            </div>

            <div className="mt-5 rounded-[28px] bg-slate-50/70 p-4">
              <div className="h-3 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={cn(
                    'h-full rounded-full transition-all duration-500',
                    metrics.progressPercent >= 100
                      ? 'bg-emerald-500'
                      : metrics.progressPercent >= 60
                        ? 'bg-sky-500'
                        : metrics.progressPercent >= 20
                          ? 'bg-amber-400'
                          : 'bg-rose-500',
                  )}
                  style={{ width: `${progressWidth}%` }}
                />
              </div>
              <p className="mt-3 text-sm text-slate-600">
                Покрывает {formatCoverageMonths(metrics.coverageMonths)} из 5 месяцев расходов
              </p>
            </div>

            <p className="mt-4 text-sm text-slate-600">{metrics.message}</p>
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