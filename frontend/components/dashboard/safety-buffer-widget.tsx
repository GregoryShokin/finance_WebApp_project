'use client';

import { useMemo } from 'react';
import { ShoppingCart } from 'lucide-react';

import { getSafetyBufferMetrics } from '@/components/dashboard/safety-buffer-data';
import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { GoalWithProgress } from '@/types/goal';

type Props = {
  goals: GoalWithProgress[];
  isLoading?: boolean;
  largePurchasesTotal?: number;
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

export function SafetyBufferWidget({ goals, isLoading = false, largePurchasesTotal = 0 }: Props) {
  const metrics = useMemo(() => getSafetyBufferMetrics(goals), [goals]);

  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'safety-buffer-widget', expandHeight: 500 });

  function renderCollapsedBody() {
    if (isLoading) {
      return (
        <div className="mt-4 space-y-2">
          <div className="h-9 w-40 animate-pulse rounded bg-slate-100" />
          <div className="h-5 w-36 animate-pulse rounded bg-slate-100" />
        </div>
      );
    }

    if (!metrics) {
      return (
        <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
          Недостаточно данных
        </div>
      );
    }

    const progressWidth = Math.max(0, Math.min(metrics.progressPercent, 100));

    return (
      <div className="mt-4">
        <MoneyAmount value={metrics.savedAmount} tone="income" className="text-2xl lg:text-3xl" />
        <p className="mt-3 text-sm text-slate-500">{formatProgress(metrics.progressPercent)} от целевого уровня</p>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
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
      </div>
    );
  }

  function renderExpandedBody() {
    if (!metrics || !isExpanded) return null;

    const progressWidth = Math.max(0, Math.min(metrics.progressPercent, 100));

    return (
      <>
        <div className="mt-4 space-y-1.5 rounded-2xl bg-slate-50 px-3 py-2.5 text-xs">
          <div className="flex items-center justify-between gap-2">
            <span className="text-slate-400">Накоплено</span>
            <span className="font-medium text-slate-900">{formatMoney(metrics.savedAmount)}</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-slate-400">Цель</span>
            <span className="font-medium text-slate-900">{formatMoney(metrics.targetAmount)}</span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-slate-400">Расходы в месяц</span>
            <span className="font-medium text-slate-900">{formatMoney(metrics.avgMonthlyExpenses)}</span>
          </div>
        </div>

        <div className="mt-3">
          <div className="h-2 overflow-hidden rounded-full bg-slate-200">
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
          <p className="mt-1.5 text-[11px] text-slate-500">
            Покрывает {formatCoverageMonths(metrics.coverageMonths)} из 5 месяцев расходов
          </p>
        </div>

        <p className="mt-3 text-[11px] leading-snug text-slate-600">{metrics.message}</p>

        {largePurchasesTotal > 0 ? (
          <div className="mt-2 flex items-start gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-2 py-1.5">
            <ShoppingCart className="mt-0.5 size-3 shrink-0 text-amber-500" />
            <p className="text-[10px] leading-snug text-amber-700">
              Средние расходы рассчитаны без крупных покупок на{' '}
              <span className="font-medium">{formatMoney(largePurchasesTotal)}</span> за 6 месяцев.
            </p>
          </div>
        ) : null}
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
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Подушка безопасности</p>
          {toggleButton}
          {renderCollapsedBody()}
          {renderExpandedBody()}
        </Card>
      </div>
    </div>
  );
}
