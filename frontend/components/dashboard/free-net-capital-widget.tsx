'use client';

import { useMemo, useRef, useEffect, useState } from 'react';
import { Info } from 'lucide-react';
import { getMonthProgressMetrics, MonthProgressMetrics, BarStatus } from '@/components/dashboard/free-net-capital-data';
import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { resolveExpandDirection, resolveExpandUp } from '@/lib/utils/widget-expand';
import type { BudgetProgress } from '@/types/budget';
import type { Transaction } from '@/types/transaction';

type Props = {
  budgetProgress: BudgetProgress[];
  transactions: Transaction[];
  isLoading?: boolean;
};

function barColor(status: BarStatus): string {
  if (status === 'danger') return '#E24B4A';
  if (status === 'warning') return '#EF9F27';
  return '#1D9E75';
}

function statusBadgeClass(status: MonthProgressMetrics['status']): string {
  if (status === 'danger') return 'bg-rose-50 text-rose-700';
  if (status === 'warning') return 'bg-amber-50 text-amber-700';
  if (status === 'no_data') return 'bg-slate-100 text-slate-500';
  return 'bg-emerald-50 text-emerald-700';
}

function statusLabel(status: MonthProgressMetrics['status']): string {
  if (status === 'danger') return 'Опережаешь бюджет';
  if (status === 'warning') return 'Чуть выше нормы';
  if (status === 'no_data') return 'Нет данных';
  return 'В рамках бюджета';
}

function ProgressRow({
  label,
  spentPercent,
  timePercent,
  status,
  spentAmount,
  plannedAmount,
  topCategory,
  showRemaining = false,
  compact = false,
}: {
  label: string;
  spentPercent: number;
  timePercent: number;
  status: BarStatus;
  spentAmount: number;
  plannedAmount: number;
  topCategory: string | null;
  showRemaining?: boolean;
  compact?: boolean;
}) {
  const clampedSpent = Math.min(spentPercent, 100);
  const color = barColor(status);
  const remainingAmount = plannedAmount - spentAmount;
  const remainingLabel = remainingAmount >= 0
    ? `осталось ${formatMoney(remainingAmount)}`
    : `перерасход ${formatMoney(Math.abs(remainingAmount))}`;

  return (
    <div className={compact ? 'space-y-1' : 'space-y-2'}>
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="text-slate-500">
          {spentPercent}%
          {!compact && plannedAmount > 0 && (
            <span className="ml-1 text-slate-400">
              {showRemaining
                ? `(${remainingLabel})`
                : `(${formatMoney(spentAmount)} из ${formatMoney(plannedAmount)})`}
            </span>
          )}
        </span>
      </div>

      <div className="relative h-3 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="absolute top-0 bottom-0 z-10 w-0.5 bg-slate-400"
          style={{ left: `${timePercent}%` }}
        />
        <div
          className="absolute top-0 left-0 h-full rounded-full transition-all duration-500"
          style={{ width: `${clampedSpent}%`, backgroundColor: color }}
        />
      </div>

      {!compact && topCategory && status !== 'good' && (
        <p className="text-xs text-slate-400">
          Больше всего — <span className="text-slate-600">{topCategory}</span>
        </p>
      )}
    </div>
  );
}

export function FreeNetCapitalWidget({
  budgetProgress,
  transactions,
  isLoading = false,
}: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState(0);
  const [expandDirection, setExpandDirection] = useState<'left' | 'right'>('right');
  const [expandUp, setExpandUp] = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const metrics = useMemo(
    () => getMonthProgressMetrics(budgetProgress, transactions),
    [budgetProgress, transactions],
  );

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, isLoading, metrics]);

  useEffect(() => {
    if (!isExpanded) return;
    function handleClick(e: MouseEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) setIsExpanded(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded]);

  useEffect(() => {
    function handleExternal(e: Event) {
      const ce = e as CustomEvent<{ source?: string; open?: boolean }>;
      if (ce.detail?.source !== 'month-progress-widget' && ce.detail?.open) {
        setIsExpanded(false);
      }
    }
    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternal as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternal as EventListener);
  }, []);

  function handleToggle() {
    if (!isExpanded && cardRef.current) {
      setExpandDirection(resolveExpandDirection(cardRef.current, 860));
      setExpandUp(resolveExpandUp(cardRef.current, 500));
    }
    setIsExpanded((v) => {
      const next = !v;
      document.dispatchEvent(new CustomEvent(FI_SCORE_WIDGET_EVENT, {
        detail: { source: 'month-progress-widget', open: next },
      }));
      return next;
    });
  }

  function renderHeader() {
    return (
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-slate-500">Прогресс месяца</p>
          <p className="mt-0.5 text-xs capitalize text-slate-400">{metrics.monthLabel}</p>
        </div>
        <button
          type="button"
          onClick={handleToggle}
          className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
          aria-label="Подробнее"
          aria-expanded={isExpanded}
        >
          <Info className="size-3.5" />
        </button>
      </div>
    );
  }

  function renderCollapsedBody() {
    if (isLoading) {
      return (
        <div className="mt-4 space-y-3">
          <div className="h-4 w-32 animate-pulse rounded bg-slate-100" />
          <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
          <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
          <div className="h-3 w-full animate-pulse rounded bg-slate-100" />
        </div>
      );
    }

    return (
      <div className="mt-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className={cn(
            'rounded-full px-2.5 py-1 text-xs font-medium',
            statusBadgeClass(metrics.status),
          )}>
            {statusLabel(metrics.status)}
          </span>
          <span className="text-xs text-slate-400">
            {metrics.daysPassed} из {metrics.daysTotal} дней
          </span>
        </div>

        <div className="space-y-1">
          <div className="flex justify-between text-xs text-slate-400">
            <span>Месяц прошёл</span>
            <span>{metrics.timePercent}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-slate-300 transition-all duration-500"
              style={{ width: `${metrics.timePercent}%` }}
            />
          </div>
        </div>

        <ProgressRow
          label="Обязательные"
          spentPercent={metrics.essential.spentPercent}
          timePercent={metrics.timePercent}
          status={metrics.essential.status}
          spentAmount={metrics.essential.spentAmount}
          plannedAmount={metrics.essential.plannedAmount}
          topCategory={null}
          compact
        />

        <ProgressRow
          label="Второстепенные"
          spentPercent={metrics.secondary.spentPercent}
          timePercent={metrics.timePercent}
          status={metrics.secondary.status}
          spentAmount={metrics.secondary.spentAmount}
          plannedAmount={metrics.secondary.plannedAmount}
          topCategory={null}
          compact
        />
      </div>
    );
  }

  function renderExpandedBody() {
    if (!isExpanded) return null;

    return (
      <div className="mt-5 space-y-5">
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-slate-400">
            <span>Месяц прошёл</span>
            <span>{metrics.daysPassed} из {metrics.daysTotal} дней · {metrics.timePercent}%</span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-slate-300 transition-all"
              style={{ width: `${metrics.timePercent}%` }}
            />
          </div>
        </div>

        <ProgressRow
          label="Обязательные расходы"
          spentPercent={metrics.essential.spentPercent}
          timePercent={metrics.timePercent}
          status={metrics.essential.status}
          spentAmount={metrics.essential.spentAmount}
          plannedAmount={metrics.essential.plannedAmount}
          topCategory={metrics.essential.topCategory}
          showRemaining
          compact={false}
        />

        <ProgressRow
          label="Второстепенные расходы"
          spentPercent={metrics.secondary.spentPercent}
          timePercent={metrics.timePercent}
          status={metrics.secondary.status}
          spentAmount={metrics.secondary.spentAmount}
          plannedAmount={metrics.secondary.plannedAmount}
          topCategory={metrics.secondary.topCategory}
          showRemaining
          compact={false}
        />

        {!metrics.hasData && (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
            Задай бюджет по категориям в разделе Планирование — тогда виджет
            покажет насколько ты укладываешься в план.
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative self-start overflow-visible"
      style={{ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }}
    >
      {isExpanded && (
        <button
          type="button"
          aria-label="Закрыть"
          onClick={handleToggle}
          className="fixed inset-0 z-40 bg-black/10"
        />
      )}

      <div ref={cardRef}>
        <Card className="relative overflow-visible p-5">
          {renderHeader()}
          {renderCollapsedBody()}
        </Card>
      </div>

      <Card
        className="absolute overflow-visible p-5"
        style={{
          position: isExpanded ? 'absolute' : 'relative',
          top: isExpanded && !expandUp ? 0 : 'auto',
          bottom: isExpanded && expandUp ? 0 : 'auto',
          left: isExpanded && expandDirection === 'right' ? 0 : 'auto',
          right: isExpanded && expandDirection === 'left' ? 0 : 'auto',
          transform: isExpanded ? 'scale(1)' : 'scale(0.6)',
          width: isExpanded ? 'min(860px, calc(100vw - 2rem))' : '100%',
          transformOrigin: expandUp
            ? (expandDirection === 'right' ? 'bottom left' : 'bottom right')
            : (expandDirection === 'right' ? 'top left' : 'top right'),
          transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1), opacity 300ms ease',
          opacity: isExpanded ? 1 : 0,
          zIndex: isExpanded ? 50 : 1,
          overflow: 'visible',
          boxShadow: isExpanded ? '0 8px 40px rgba(0,0,0,0.12)' : 'none',
          pointerEvents: isExpanded ? 'auto' : 'none',
        }}
      >
        {renderHeader()}
        {renderExpandedBody()}
      </Card>
    </div>
  );
}
