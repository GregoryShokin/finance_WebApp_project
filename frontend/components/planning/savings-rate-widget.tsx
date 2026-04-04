'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { resolveExpandUp } from '@/lib/utils/widget-expand';
import type { Category } from '@/types/category';
import type { FinancialHealth } from '@/types/financial-health';
import type { Transaction } from '@/types/transaction';

const SCALE = 1.8;

type Props = {
  health: FinancialHealth | null | undefined;
  transactions: Transaction[];
  categories: Category[];
  isLoading?: boolean;
};

type MonthlyPoint = {
  key: string;
  label: string;
  income: number;
  totalExpenses: number;
  essentialExpenses: number;
  wantsExpenses: number;
  savingsRate: number;
};

function getSavingsZone(value: number) {
  if (value > 30) return { label: 'Отлично', badgeClass: 'bg-teal-100 text-teal-700', color: '#0F6E56' };
  if (value > 20) return { label: 'Хорошо', badgeClass: 'bg-emerald-100 text-emerald-700', color: '#1D9E75' };
  if (value >= 10) return { label: 'Норма', badgeClass: 'bg-blue-100 text-blue-700', color: '#2563EB' };
  if (value >= 0) return { label: 'Слабо', badgeClass: 'bg-amber-100 text-amber-700', color: '#EF9F27' };
  return { label: 'Дефицит', badgeClass: 'bg-rose-100 text-rose-700', color: '#E24B4A' };
}

function monthKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function shiftMonth(base: Date, offset: number): Date {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

function mean(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function SavingsRateWidget({ health, transactions, categories, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);
  const [progressWidth, setProgressWidth] = useState(0);
  const [expandUp, setExpandUp] = useState(false);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, isLoading, health, transactions, categories]);

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

  const analyticsTransactions = useMemo(
    () => transactions.filter((transaction) => transaction.affects_analytics),
    [transactions],
  );

  const metrics = useMemo(() => {
    if (!health || analyticsTransactions.length === 0) {
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

    const firstDate = new Date(firstTransaction.transaction_date);
    const monthsTracked = (today.getFullYear() - firstDate.getFullYear()) * 12 + (today.getMonth() - firstDate.getMonth());
    const requestedMonths = Math.max(0, Math.min(monthsTracked, 6));

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
        label: pointDate.toLocaleString('ru-RU', { month: 'short' }).replace('.', ''),
        income: 0,
        totalExpenses: 0,
        essentialExpenses: 0,
        wantsExpenses: 0,
        savingsRate: 0,
      });
    }

    for (const transaction of analyticsTransactions) {
      const txDate = new Date(transaction.transaction_date);
      const key = monthKey(txDate);
      const bucket = monthBuckets.get(key);
      if (!bucket) continue;

      const amount = Number(transaction.amount);
      if (transaction.type === 'income') {
        bucket.income += amount;
        continue;
      }

      if (transaction.type !== 'expense') continue;
      bucket.totalExpenses += amount;

      const priority = categoriesById.get(transaction.category_id ?? -1)?.priority ?? transaction.category_priority ?? null;
      if (priority === 'expense_essential') {
        bucket.essentialExpenses += amount;
      } else {
        bucket.wantsExpenses += amount;
      }
    }

    const monthlyData = monthOrder
      .map((key) => monthBuckets.get(key))
      .filter((bucket): bucket is MonthlyPoint => Boolean(bucket && (bucket.income > 0 || bucket.totalExpenses > 0)))
      .map((bucket) => ({
        ...bucket,
        savingsRate: bucket.income > 0 ? ((bucket.income - bucket.totalExpenses) / bucket.income) * 100 : 0,
      }));

    if (monthlyData.length === 0) {
      return null;
    }

    const avgIncome = mean(monthlyData.map((month) => month.income));
    const essentialAvg = mean(monthlyData.map((month) => month.essentialExpenses));
    const wantsAvg = mean(monthlyData.map((month) => month.wantsExpenses));
    const savingsAvg = mean(monthlyData.map((month) => month.income - month.totalExpenses));
    const averageSavingsRate = mean(monthlyData.map((month) => month.savingsRate));
    const monthlyAvgBalance = mean(monthlyData.map((month) => month.income - month.totalExpenses));

    const essentialPct = avgIncome > 0 ? (essentialAvg / avgIncome) * 100 : 0;
    const wantsPct = avgIncome > 0 ? (wantsAvg / avgIncome) * 100 : 0;
    const savingsPct = avgIncome > 0 ? (savingsAvg / avgIncome) * 100 : 0;

    return {
      monthsUsed: monthlyData.length,
      averageSavingsRate,
      essentialAvg,
      wantsAvg,
      savingsAvg,
      essentialPct,
      wantsPct,
      savingsPct,
      monthlyAvgBalance,
    };
  }, [analyticsTransactions, categories, health]);

  const zone = getSavingsZone(metrics?.averageSavingsRate ?? 0);
  const targetWidth = Math.min(Math.max(metrics?.averageSavingsRate ?? 0, 0), 100);

  useEffect(() => {
    setProgressWidth(targetWidth);
  }, [targetWidth]);

  function handleToggle(next?: boolean) {
    if ((!isExpanded || next === true) && cardRef.current) {
      setExpandUp(resolveExpandUp(cardRef.current, 450));
    }
    setIsExpanded((value) => next ?? !value);
  }

  function renderRuleRow(label: string, pct: number, avg: number, target: number, goodColor: string, warnColor: string, badColor: string, emphasizePositive = false) {
    const color = emphasizePositive
      ? pct >= 20
        ? goodColor
        : pct >= 10
          ? warnColor
          : badColor
      : pct > target + 10
        ? badColor
        : pct > target
          ? warnColor
          : goodColor;

    return (
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className="text-sm text-slate-600">{label}</span>
          <div className="flex items-center gap-2">
            <span className={cn('text-sm font-medium', emphasizePositive ? (pct >= 20 ? 'text-emerald-600' : 'text-rose-600') : pct > target ? 'text-rose-600' : 'text-slate-900')}>
              {pct.toFixed(0)}%
            </span>
            <span className="text-xs text-slate-400">цель {target}%</span>
          </div>
        </div>
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{ width: `${Math.min(Math.max(pct, 0), 100)}%`, background: color }}
          />
          <div className="absolute top-0 h-full w-0.5 bg-slate-400" style={{ left: `${target}%` }} />
        </div>
        <p className="mt-0.5 text-right text-xs text-slate-400">{formatMoney(avg)} / мес</p>
      </div>
    );
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Норма сбережений</p>
          <div className="mt-3 space-y-2">
            <div className="h-9 w-24 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-20 animate-pulse rounded-full bg-slate-100" />
            <div className="h-2 w-full animate-pulse rounded-full bg-slate-100" />
          </div>
        </>
      );
    }

    if (!metrics || metrics.monthsUsed < 1) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Норма сбережений</p>
          <div className="mt-3">
            <p className="text-3xl font-medium text-slate-300">-</p>
            <p className="mt-2 text-sm text-slate-400">Недостаточно данных для расчёта</p>
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Норма сбережений</p>

        <button
          type="button"
          onClick={() => handleToggle()}
          className="absolute right-3 top-3 flex size-[22px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
          aria-label="Подробнее"
          aria-expanded={isExpanded}
        >
          i
        </button>

        <p className="mt-2 text-3xl font-medium" style={{ color: zone.color }}>
          {metrics.averageSavingsRate.toFixed(1)}%
        </p>

        <span className={cn('mt-1.5 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium', zone.badgeClass)}>
          {zone.label}
        </span>

        <div className="mt-3">
          <div className="relative h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full transition-all duration-[800ms] ease-out"
              style={{ width: `${progressWidth}%`, backgroundColor: zone.color }}
            />
            <div className="absolute top-0 h-full w-0.5 bg-slate-400" style={{ left: '20%' }} />
          </div>
          <div className="mt-1 flex items-center justify-between text-[10px] text-slate-300">
            <span>0%</span>
            <span>20% (цель)</span>
            <span>100%</span>
          </div>
        </div>

        <p className="mt-2 text-xs text-slate-400">среднее за {metrics.monthsUsed} мес.</p>

        {isExpanded ? (
          <>
            <hr className="my-3 border-slate-100" />

            <div className="space-y-3">
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
                Распределение по правилу 50/30/20
              </p>

              {renderRuleRow('Обязательные', metrics.essentialPct, metrics.essentialAvg, 50, '#1D9E75', '#EF9F27', '#E24B4A')}
              {renderRuleRow('Второстепенные', metrics.wantsPct, metrics.wantsAvg, 30, '#1D9E75', '#EF9F27', '#E24B4A')}
              {renderRuleRow('Сбережения', metrics.savingsPct, metrics.savingsAvg, 20, '#1D9E75', '#EF9F27', '#E24B4A', true)}
            </div>

            <div className="mt-3 flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2.5">
              <div>
                <p className="text-sm font-medium text-slate-900">Среднемесячный остаток</p>
                <p className="text-xs text-slate-400">за {metrics.monthsUsed} мес.</p>
              </div>
              <MoneyAmount
                value={metrics.monthlyAvgBalance}
                tone={metrics.monthlyAvgBalance >= 0 ? 'income' : 'expense'}
                className="text-base font-semibold"
              />
            </div>
          </>
        ) : null}
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
          onClick={() => handleToggle(false)}
          className="fixed inset-0 z-40 bg-black/10"
        />
      ) : null}

      <div ref={cardRef}>
        <Card
          className="relative overflow-visible p-5"
          style={{
            position: isExpanded ? 'absolute' : 'relative',
            top: isExpanded && !expandUp ? 0 : 'auto',
            bottom: isExpanded && expandUp ? 0 : 'auto',
            left: 0,
            right: 0,
            transform: isExpanded ? `scale(${SCALE})` : 'scale(1)',
            transformOrigin: expandUp ? 'center bottom' : 'center center',
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
