'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import type { Category } from '@/types/category';
import type { Transaction } from '@/types/transaction';

const MAX_MONTHS = 6;

type Props = {
  transactions: Transaction[];
  categories: Category[];
  isLoading?: boolean;
};

type MonthlyPoint = {
  key: string;
  income: number;
  essential: number;
  secondary: number;
  balance: number;
};

type StructureMetrics = {
  monthsUsed: number;
  avgIncome: number;
  essentialShare: number;
  secondaryShare: number;
  balanceShare: number;
  summary: string;
  hasNegativeBalance: boolean;
};

function shiftMonth(base: Date, offset: number) {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function startOfMonth(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

function mean(values: number[]) {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function clampWidth(value: number) {
  return Math.min(Math.max(value, 0), 100);
}

function getBarTone(value: number, target: number, inverse = false) {
  if (inverse) {
    if (value >= target) return 'bg-emerald-500';
    if (value >= target * 0.75) return 'bg-amber-400';
    return 'bg-rose-500';
  }

  if (value <= target) return 'bg-emerald-500';
  if (value <= target + 10) return 'bg-amber-400';
  return 'bg-rose-500';
}

function buildSummary(essentialShare: number, secondaryShare: number, balanceShare: number) {
  const issues: string[] = [];

  if (essentialShare > 60) {
    issues.push('Обязательные расходы заметно выше нормы');
  } else if (essentialShare > 50) {
    issues.push('Обязательные расходы выше нормы');
  }

  if (secondaryShare > 40) {
    issues.push('Второстепенные расходы значительно превышают норму');
  } else if (secondaryShare > 30) {
    issues.push('Второстепенные расходы выше нормы');
  }

  if (balanceShare < 0) {
    issues.push('Остаток ушел в отрицательную зону');
  } else if (balanceShare < 20) {
    issues.push('Остаток ниже целевого уровня');
  }

  if (issues.length === 0) {
    return 'Структура близка к рекомендуемой';
  }

  return issues.slice(0, 2).join('. ');
}

function renderBarRow(label: string, value: number, target: number, toneClass: string, inverse = false) {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3">
        <span className="text-sm text-slate-600">{label}</span>
        <div className="flex items-center gap-2 text-sm">
          <span className={cn('font-semibold', inverse ? (value >= 0 ? 'text-slate-900' : 'text-rose-600') : 'text-slate-900')}>
            {value.toFixed(1)}%
          </span>
          <span className="text-xs text-slate-400">цель {target}%</span>
        </div>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-100">
        <div className={cn('h-full rounded-full transition-all duration-500', toneClass)} style={{ width: `${clampWidth(value)}%` }} />
        <div className="absolute top-0 h-full w-0.5 bg-slate-500" style={{ left: `${target}%` }} />
      </div>
    </div>
  );
}

export function IncomeStructureWidget({ transactions, categories, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, isLoading, transactions, categories]);

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
      if (customEvent.detail?.source !== 'income-structure-widget' && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, []);

  const metrics = useMemo<StructureMetrics | null>(() => {
    const analyticsTransactions = transactions.filter((transaction) => transaction.affects_analytics);
    if (analyticsTransactions.length === 0) {
      return null;
    }

    const categoriesById = new Map(categories.map((category) => [category.id, category]));
    const today = new Date();
    const sortedTransactions = [...analyticsTransactions].sort(
      (left, right) => new Date(left.transaction_date).getTime() - new Date(right.transaction_date).getTime(),
    );
    const firstTransaction = sortedTransactions[0];
    if (!firstTransaction) {
      return null;
    }

    const firstDate = startOfMonth(new Date(firstTransaction.transaction_date));
    const monthsTracked =
      (today.getFullYear() - firstDate.getFullYear()) * 12 + (today.getMonth() - firstDate.getMonth());
    const requestedMonths = Math.max(0, Math.min(monthsTracked, MAX_MONTHS));
    if (requestedMonths < 1) {
      return null;
    }

    const monthBuckets = new Map<string, MonthlyPoint>();
    const monthOrder: string[] = [];

    for (let offset = requestedMonths; offset >= 1; offset -= 1) {
      const pointDate = shiftMonth(today, -offset);
      const key = monthKey(pointDate);
      monthOrder.push(key);
      monthBuckets.set(key, {
        key,
        income: 0,
        essential: 0,
        secondary: 0,
        balance: 0,
      });
    }

    for (const transaction of analyticsTransactions) {
      const bucket = monthBuckets.get(monthKey(new Date(transaction.transaction_date)));
      if (!bucket) continue;

      const amount = Number(transaction.amount);
      if (transaction.type === 'income') {
        bucket.income += amount;
        continue;
      }

      if (transaction.type !== 'expense') continue;

      const priority = categoriesById.get(transaction.category_id ?? -1)?.priority ?? transaction.category_priority ?? null;
      if (priority === 'expense_essential') {
        bucket.essential += amount;
      } else {
        bucket.secondary += amount;
      }
    }

    const populatedMonths = monthOrder
      .map((key) => monthBuckets.get(key))
      .filter((bucket): bucket is MonthlyPoint => Boolean(bucket))
      .filter((bucket) => bucket.income > 0 || bucket.essential > 0 || bucket.secondary > 0)
      .map((bucket) => ({
        ...bucket,
        balance: bucket.income - bucket.essential - bucket.secondary,
      }));

    if (populatedMonths.length === 0) {
      return null;
    }

    const avgIncome = mean(populatedMonths.map((month) => month.income));
    if (avgIncome <= 0) {
      return null;
    }

    const avgEssentialExpenses = mean(populatedMonths.map((month) => month.essential));
    const avgSecondaryExpenses = mean(populatedMonths.map((month) => month.secondary));
    const avgMonthlyBalance = mean(populatedMonths.map((month) => month.balance));

    const essentialShare = (avgEssentialExpenses / avgIncome) * 100;
    const secondaryShare = (avgSecondaryExpenses / avgIncome) * 100;
    const balanceShare = (avgMonthlyBalance / avgIncome) * 100;

    return {
      monthsUsed: populatedMonths.length,
      avgIncome,
      essentialShare,
      secondaryShare,
      balanceShare,
      summary: buildSummary(essentialShare, secondaryShare, balanceShare),
      hasNegativeBalance: balanceShare < 0,
    };
  }, [transactions, categories]);

  function handleToggle() {
    setIsExpanded((current) => {
      const next = !current;
      document.dispatchEvent(
        new CustomEvent(FI_SCORE_WIDGET_EVENT, {
          detail: { source: 'income-structure-widget', open: next },
        }),
      );
      return next;
    });
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-semibold text-slate-900">Структура дохода</p>
          <p className="mt-1 text-sm text-slate-500">по правилу 50/30/20</p>
          <div className="mt-4 space-y-3">
            <div className="h-12 animate-pulse rounded-2xl bg-slate-50" />
            <div className="h-12 animate-pulse rounded-2xl bg-slate-50" />
            <div className="h-12 animate-pulse rounded-2xl bg-slate-50" />
          </div>
        </>
      );
    }

    if (!metrics) {
      return (
        <>
          <div className="pr-10">
            <p className="text-sm font-semibold text-slate-900">Структура дохода</p>
            <p className="mt-1 text-sm text-slate-500">по правилу 50/30/20</p>
          </div>
          <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
            Недостаточно данных по доходам для построения структуры.
          </div>
        </>
      );
    }

    return (
      <>
        <div className="flex items-start justify-between gap-4">
          <div className="pr-4">
            <h4 className="text-base font-semibold text-slate-900">Структура дохода</h4>
            <p className="mt-1 text-sm text-slate-500">
              {isExpanded ? 'Сравнение с рекомендуемой моделью 50/30/20' : 'по правилу 50/30/20'}
            </p>
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

        <div className="mt-4 space-y-4">
          {renderBarRow('Обязательные', metrics.essentialShare, 50, getBarTone(metrics.essentialShare, 50))}
          {renderBarRow('Второстепенные', metrics.secondaryShare, 30, getBarTone(metrics.secondaryShare, 30))}
          {renderBarRow('Остаток', metrics.balanceShare, 20, getBarTone(metrics.balanceShare, 20, true), true)}
        </div>

        {isExpanded ? (
          <>
            {metrics.hasNegativeBalance ? (
              <div className="mt-4 rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
                Остаток отрицательный: факт отображается как значение ниже нуля, а шкала ограничена от 0 до 100%.
              </div>
            ) : null}
            <p className="mt-4 text-sm text-slate-600">{metrics.summary}</p>
          </>
        ) : null}
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
            'relative overflow-visible transition-[width,transform,box-shadow] duration-300 ease-out',
            isExpanded
              ? 'absolute right-0 top-0 z-50 w-[min(720px,calc(100vw-2rem))] p-5 shadow-2xl lg:p-6 xl:w-[720px]'
              : 'w-full p-4 lg:p-5',
          )}
          style={{
            transformOrigin: 'right top',
            transform: isExpanded ? 'translateY(-4px)' : 'translateY(0)',
          }}
        >
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}
