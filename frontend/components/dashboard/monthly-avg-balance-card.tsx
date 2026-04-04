'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Info } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { Category } from '@/types/category';
import type { FinancialHealth } from '@/types/financial-health';
import type { GoalWithProgress } from '@/types/goal';
import type { Transaction } from '@/types/transaction';

const SCALE = 1.8;
const MAX_MONTHS = 6;

type Props = {
  health: FinancialHealth;
  transactions: Transaction[];
  categories: Category[];
  goals: GoalWithProgress[];
  isExpanded: boolean;
  onToggle: () => void;
};

type ScenarioKey = 'deficit' | 'dti' | 'buffer' | 'investments';

type GoalForecast = {
  id: number;
  name: string;
  percent: number;
  remaining: number;
  monthlyNeeded: number | null;
  months: number | null;
};

type SecondaryCategory = {
  id: number;
  name: string;
  avgAmount: number;
  shareOfTop: number;
  reductionAmount: number;
};

type Metrics = {
  avgMonthlyIncome: number;
  avgMonthlyExpense: number;
  avgMonthlyBalance: number;
  monthsUsed: number;
  negativeMonths: number;
  safetyBufferMonths: number;
  safetyBufferSaved: number;
  activeGoals: GoalForecast[];
  nearestGoal: GoalForecast | null;
  topSecondary: SecondaryCategory[];
  reductionPercent: number | null;
  monthlyAllocationPerGoal: number | null;
};

function startOfMonth(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

function shiftMonth(base: Date, offset: number) {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function mean(values: number[]) {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function formatMonths(value: number | null) {
  if (value === null || !Number.isFinite(value)) return '—';
  return `${Math.ceil(value)} мес.`;
}

function ProgressBar({ value, toneClass, markerPercent, markerClass = 'bg-slate-500' }: { value: number; toneClass: string; markerPercent?: number; markerClass?: string }) {
  const width = clamp(value, 0, 100);

  return (
    <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-100">
      <div className={cn('h-full rounded-full transition-all duration-500', toneClass)} style={{ width: `${width}%` }} />
      {markerPercent !== undefined ? (
        <div className={cn('absolute top-0 h-full w-0.5', markerClass)} style={{ left: `${clamp(markerPercent, 0, 100)}%` }} />
      ) : null}
    </div>
  );
}

function getDtiTone(dti: number) {
  if (dti < 30) return { badge: 'bg-emerald-100 text-emerald-700', bar: 'bg-emerald-500' };
  if (dti < 40) return { badge: 'bg-amber-100 text-amber-700', bar: 'bg-amber-400' };
  return { badge: 'bg-rose-100 text-rose-700', bar: 'bg-rose-500' };
}

function getScenario(health: FinancialHealth, safetyBufferMonths: number): ScenarioKey {
  if (health.monthly_avg_balance < 0) return 'deficit';
  if (health.dti >= 40) return 'dti';
  if (safetyBufferMonths < 3) return 'buffer';
  return 'investments';
}

function buildMetrics(health: FinancialHealth, transactions: Transaction[], categories: Category[], goals: GoalWithProgress[]): Metrics {
  const analyticsTransactions = transactions.filter((transaction) => transaction.affects_analytics);
  const today = new Date();
  const currentMonth = startOfMonth(today);
  const lastCompletedMonth = shiftMonth(currentMonth, -1);

  if (analyticsTransactions.length === 0) {
    return {
      avgMonthlyIncome: 0,
      avgMonthlyExpense: 0,
      avgMonthlyBalance: health.monthly_avg_balance,
      monthsUsed: 0,
      negativeMonths: 0,
      safetyBufferMonths: 0,
      safetyBufferSaved: 0,
      activeGoals: [],
      nearestGoal: null,
      topSecondary: [],
      reductionPercent: null,
      monthlyAllocationPerGoal: null,
    };
  }

  const sortedTransactions = [...analyticsTransactions].sort(
    (left, right) => new Date(left.transaction_date).getTime() - new Date(right.transaction_date).getTime(),
  );

  const firstTrackedMonth = sortedTransactions[0]
    ? startOfMonth(new Date(sortedTransactions[0].transaction_date))
    : lastCompletedMonth;
  const monthsTracked =
    (today.getFullYear() - firstTrackedMonth.getFullYear()) * 12 + (today.getMonth() - firstTrackedMonth.getMonth());
  const requestedMonths = Math.max(0, Math.min(monthsTracked, MAX_MONTHS));

  if (requestedMonths < 1) {
    const avgMonthlyExpenses = Number(health.avg_monthly_expenses ?? 0);
    const safetyGoal = goals.find((goal) => goal.system_key === 'safety_buffer');
    const safetyBufferSaved = Number(safetyGoal?.saved ?? 0);
    const safetyBufferMonths = avgMonthlyExpenses > 0 ? safetyBufferSaved / avgMonthlyExpenses : 0;

    return {
      avgMonthlyIncome: 0,
      avgMonthlyExpense: 0,
      avgMonthlyBalance: health.monthly_avg_balance,
      monthsUsed: 0,
      negativeMonths: 0,
      safetyBufferMonths,
      safetyBufferSaved,
      activeGoals: [],
      nearestGoal: null,
      topSecondary: [],
      reductionPercent: null,
      monthlyAllocationPerGoal: null,
    };
  }

  const candidateStart = shiftMonth(lastCompletedMonth, -(requestedMonths - 1));
  const startMonth = firstTrackedMonth > candidateStart ? firstTrackedMonth : candidateStart;

  const monthOrder: Date[] = [];
  for (let cursor = new Date(startMonth.getTime()); cursor <= lastCompletedMonth; cursor = shiftMonth(cursor, 1)) {
    monthOrder.push(new Date(cursor.getTime()));
  }

  const monthBuckets = new Map<string, { income: number; expense: number; balance: number }>();
  for (const month of monthOrder) {
    monthBuckets.set(monthKey(month), { income: 0, expense: 0, balance: 0 });
  }

  const categoryMap = new Map(categories.map((category) => [category.id, category]));
  const secondaryTotals = new Map<number, number>();

  for (const transaction of analyticsTransactions) {
    const date = new Date(transaction.transaction_date);
    const key = monthKey(date);
    const bucket = monthBuckets.get(key);
    if (!bucket) continue;

    const amount = Number(transaction.amount);
    if (transaction.type === 'income') {
      bucket.income += amount;
    } else if (transaction.type === 'expense') {
      bucket.expense += amount;

      const priority = categoryMap.get(transaction.category_id ?? -1)?.priority ?? transaction.category_priority ?? null;
      if (priority === 'expense_secondary' && transaction.category_id !== null) {
        secondaryTotals.set(transaction.category_id, (secondaryTotals.get(transaction.category_id) ?? 0) + amount);
      }
    }
  }

  const monthlyPoints = monthOrder.map((month) => {
    const key = monthKey(month);
    const bucket = monthBuckets.get(key) ?? { income: 0, expense: 0, balance: 0 };
    const balance = bucket.income - bucket.expense;
    return {
      key,
      income: bucket.income,
      expense: bucket.expense,
      balance,
    };
  });

  const avgMonthlyIncome = mean(monthlyPoints.map((point) => point.income));
  const avgMonthlyExpense = mean(monthlyPoints.map((point) => point.expense));
  const avgMonthlyBalance = mean(monthlyPoints.map((point) => point.balance));
  const negativeMonths = monthlyPoints.filter((point) => point.balance < 0).length;

  const safetyGoal = goals.find((goal) => goal.system_key === 'safety_buffer');
  const avgMonthlyExpenses = Number(health.avg_monthly_expenses ?? 0);
  const safetyBufferSaved = Number(safetyGoal?.saved ?? 0);
  const safetyBufferMonths = avgMonthlyExpenses > 0 ? safetyBufferSaved / avgMonthlyExpenses : 0;

  const activeGoals = goals
    .filter((goal) => goal.status !== 'archived' && goal.system_key !== 'safety_buffer')
    .map((goal) => ({
      id: goal.id,
      name: goal.name,
      percent: goal.percent,
      remaining: Number(goal.remaining ?? 0),
      monthlyNeeded: goal.monthly_needed,
      months: health.monthly_avg_balance > 0 ? Number(goal.remaining ?? 0) / health.monthly_avg_balance : null,
      deadline: goal.deadline,
    }))
    .sort((left, right) => {
      if (left.deadline && right.deadline) return new Date(left.deadline).getTime() - new Date(right.deadline).getTime();
      if (left.deadline) return -1;
      if (right.deadline) return 1;
      return left.remaining - right.remaining;
    })
    .map(({ deadline, ...goal }) => goal);

  const nearestGoal = activeGoals[0] ?? null;
  const monthlyDivisor = monthOrder.length || 1;
  const topSecondaryBase = [...secondaryTotals.entries()]
    .map(([categoryId, total]) => ({
      id: categoryId,
      name: categoryMap.get(categoryId)?.name ?? 'Без категории',
      avgAmount: total / monthlyDivisor,
    }))
    .sort((left, right) => right.avgAmount - left.avgAmount)
    .slice(0, 3);

  const topAmount = topSecondaryBase[0]?.avgAmount ?? 0;
  const topSum = topSecondaryBase.reduce((sum, item) => sum + item.avgAmount, 0);
  const reductionTarget = Math.abs(health.monthly_avg_balance);
  const reductionPercent = topSum > 0 ? Math.round((reductionTarget / topSum) * 100) : null;
  const topSecondary = topSecondaryBase.map((item) => ({
    ...item,
    shareOfTop: topAmount > 0 ? (item.avgAmount / topAmount) * 100 : 0,
    reductionAmount: topSum > 0 ? (reductionTarget * item.avgAmount) / topSum : 0,
  }));

  const monthlyAllocationPerGoal = health.monthly_avg_balance > 0 && activeGoals.length > 0 ? health.monthly_avg_balance / activeGoals.length : null;

  const goalForecasts = activeGoals.map((goal) => ({
    ...goal,
    months: monthlyAllocationPerGoal && monthlyAllocationPerGoal > 0 ? goal.remaining / monthlyAllocationPerGoal : null,
  }));

  return {
    avgMonthlyIncome,
    avgMonthlyExpense,
    avgMonthlyBalance,
    monthsUsed: monthOrder.length,
    negativeMonths,
    safetyBufferMonths,
    safetyBufferSaved,
    activeGoals: goalForecasts,
    nearestGoal,
    topSecondary,
    reductionPercent,
    monthlyAllocationPerGoal,
  };
}

export function MonthlyAvgBalanceCard({ health, transactions, categories, goals, isExpanded, onToggle }: Props) {
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const metrics = useMemo(() => buildMetrics(health, transactions, categories, goals), [health, transactions, categories, goals]);
  const scenario = useMemo(() => getScenario(health, metrics.safetyBufferMonths), [health, metrics.safetyBufferMonths]);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded, metrics, scenario]);

  useEffect(() => {
    if (!isExpanded) return;

    function handleClick(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        onToggle();
      }
    }

    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded, onToggle]);

  const dtiFreed = Math.max(0, health.dti_total_payments - health.dti_income * 0.4);
  const bufferProgress = health.avg_monthly_expenses && health.avg_monthly_expenses > 0 ? (metrics.safetyBufferMonths / 3) * 100 : 0;
  const bufferMonthsToGoal =
    health.monthly_avg_balance > 0 && health.avg_monthly_expenses && health.avg_monthly_expenses > 0 && metrics.safetyBufferMonths < 3
      ? Math.ceil(((3 - metrics.safetyBufferMonths) * health.avg_monthly_expenses) / health.monthly_avg_balance)
      : null;

  function renderCollapsedContext() {
    if (scenario === 'deficit') {
      return (
        <div className="mt-3 inline-flex rounded-full bg-rose-100 px-2.5 py-1 text-xs font-medium text-rose-700">
          {metrics.negativeMonths} месяцев в минусе
        </div>
      );
    }

    if (scenario === 'dti') {
      return <p className="mt-3 text-sm font-medium text-amber-600">Сначала снизь кредитную нагрузку</p>;
    }

    if (scenario === 'buffer') {
      return (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-medium text-sky-700">Строим подушку безопасности</p>
          <ProgressBar value={bufferProgress} toneClass="bg-sky-500" />
        </div>
      );
    }

    return metrics.nearestGoal ? (
      <div className="mt-3 space-y-2">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="truncate text-slate-600">{metrics.nearestGoal.name}</span>
          <span className="shrink-0 text-slate-400">{formatMonths(metrics.nearestGoal.months)}</span>
        </div>
        <ProgressBar value={metrics.nearestGoal.percent} toneClass="bg-emerald-500" />
      </div>
    ) : (
      <p className="mt-3 text-sm font-medium text-teal-700">Устойчивость достигнута — можно направлять остаток в капитал</p>
    );
  }

  function renderDeficitExpanded() {
    const topSum = metrics.topSecondary.reduce((sum, item) => sum + item.avgAmount, 0);

    return (
      <div className="mt-4 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl bg-slate-50 px-4 py-3">
            <p className="text-xs uppercase tracking-wide text-slate-400">Средние доходы</p>
            <p className="mt-1 font-medium text-slate-900">{formatMoney(metrics.avgMonthlyIncome)}</p>
          </div>
          <div className="rounded-2xl bg-rose-50 px-4 py-3">
            <p className="text-xs uppercase tracking-wide text-rose-400">Средние расходы</p>
            <p className="mt-1 font-medium text-rose-600">{formatMoney(metrics.avgMonthlyExpense)}</p>
          </div>
        </div>

        <div className="space-y-3">
          {metrics.topSecondary.length === 0 ? (
            <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-500">Нет второстепенных категорий для анализа.</div>
          ) : (
            metrics.topSecondary.map((item) => (
              <div key={item.id}>
                <div className="mb-1.5 flex items-center justify-between gap-3">
                  <span className="text-sm text-slate-700">{item.name}</span>
                  <span className="text-sm font-medium text-slate-900">{formatMoney(item.avgAmount)} / мес</span>
                </div>
                <ProgressBar value={item.shareOfTop} toneClass="bg-rose-500" />
              </div>
            ))
          )}
        </div>

        {metrics.topSecondary.length > 0 && topSum > 0 && metrics.reductionPercent !== null ? (
          <div className="rounded-2xl border-l-2 border-rose-400 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <p>
              Сократи эти три категории на {metrics.reductionPercent}% — и уже в следующем месяце выйдешь в плюс
            </p>
            <p className="mt-2 text-xs text-rose-600">
              {metrics.topSecondary
                .map((item) => `−${formatMoney(item.reductionAmount)} ${item.name}`)
                .join(' · ')} = +{formatMoney(Math.abs(health.monthly_avg_balance))}
            </p>
          </div>
        ) : null}
      </div>
    );
  }

  function renderDtiExpanded() {
    const dtiTone = getDtiTone(health.dti);

    return (
      <div className="mt-4 space-y-4">
        <div className="rounded-2xl bg-slate-50 px-4 py-3">
          <div className="mb-2 flex items-center justify-between gap-3 text-sm">
            <span className="text-slate-600">Текущая кредитная нагрузка</span>
            <span className={cn('font-medium', dtiTone.badge)}>{health.dti.toFixed(1)}%</span>
          </div>
          <ProgressBar value={health.dti} toneClass={dtiTone.bar} markerPercent={40} />
        </div>

        <div className="rounded-2xl border-l-2 border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <p>
            При текущем платеже {formatMoney(health.dti_total_payments)}/мес нагрузка выше нормы. После снижения кредитной нагрузки ниже 40% освободится {formatMoney(dtiFreed)} — направишь на подушку.
          </p>
        </div>
      </div>
    );
  }

  function renderBufferExpanded() {
    const futureGoals = metrics.activeGoals.slice(0, 3);

    return (
      <div className="mt-4 space-y-4">
        <div className="rounded-2xl bg-sky-50 px-4 py-3">
          <div className="mb-2 flex items-center justify-between gap-3 text-sm">
            <span className="text-sky-700">Подушка безопасности</span>
            <span className="font-medium text-sky-800">{metrics.safetyBufferMonths.toFixed(1)} из 3 мес.</span>
          </div>
          <ProgressBar value={bufferProgress} toneClass="bg-sky-500" markerPercent={100} markerClass="bg-sky-700" />
        </div>

        <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
          При текущем темпе — через {bufferMonthsToGoal ?? '—'} мес.
        </div>

        <div className="space-y-2">
          {futureGoals.length === 0 ? (
            <div className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-500">После подушки пока нет активных целей.</div>
          ) : (
            futureGoals.map((goal) => (
              <div key={goal.id} className="rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-500">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-700">{goal.name}</span>
                  <span>после подушки</span>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="rounded-2xl border-l-2 border-sky-400 bg-sky-50 px-4 py-3 text-sm text-sky-800">
          Кредиты под контролем — теперь строим защиту. Направляй {formatMoney(health.monthly_avg_balance)} остатка на подушку каждый месяц.
        </div>
      </div>
    );
  }

  function renderInvestmentsExpanded() {
    const [firstGoal, secondGoal] = metrics.activeGoals;

    return (
      <div className="mt-4 space-y-4">
        <div className="space-y-3">
          <div className="rounded-2xl border-l-2 border-teal-500 bg-teal-50 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm font-medium text-teal-800">Инвестиции</span>
              <span className="text-sm text-teal-700">{formatMoney(health.monthly_avg_balance * 0.5)}</span>
            </div>
          </div>

          {firstGoal ? (
            <div className="rounded-2xl border-l-2 border-sky-500 bg-sky-50 px-4 py-3">
              <div className="mb-2 flex items-center justify-between gap-3 text-sm">
                <span className="font-medium text-sky-800">{firstGoal.name}</span>
                <span className="text-sky-700">{formatMonths(firstGoal.months)}</span>
              </div>
              <ProgressBar value={firstGoal.percent} toneClass="bg-sky-500" />
            </div>
          ) : null}

          {secondGoal ? (
            <div className="rounded-2xl border-l-2 border-emerald-500 bg-emerald-50 px-4 py-3">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-medium text-emerald-800">{secondGoal.name}</span>
                <span className="text-emerald-700">{formatMonths(secondGoal.months)}</span>
              </div>
            </div>
          ) : null}
        </div>

        <div className="space-y-2">
          {metrics.activeGoals.slice(0, 3).map((goal) => (
            <div key={goal.id} className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <span>{goal.name}</span>
              <span>{formatMonths(goal.months)}</span>
            </div>
          ))}
        </div>

        <div className="rounded-2xl border-l-2 border-teal-500 bg-teal-50 px-4 py-3 text-sm text-teal-800">
          Устойчивость достигнута — пора растить капитал. Инвестируй регулярно — это путь к финансовой свободе.
        </div>
      </div>
    );
  }

  function renderExpandedContent() {
    if (scenario === 'deficit') return renderDeficitExpanded();
    if (scenario === 'dti') return renderDtiExpanded();
    if (scenario === 'buffer') return renderBufferExpanded();
    return renderInvestmentsExpanded();
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
          onClick={onToggle}
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
          <div className="flex items-start justify-between gap-4">
            <div className="pr-4">
              <p className="text-sm font-medium text-slate-500">Среднемесячный остаток</p>
            </div>
            <button
              type="button"
              onClick={onToggle}
              className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
              aria-label="Подробнее"
              aria-expanded={isExpanded}
            >
              <Info className="size-3.5" />
            </button>
          </div>

          <div className="mt-4">
            <p className={cn('text-2xl font-semibold lg:text-3xl', health.monthly_avg_balance >= 0 ? 'text-slate-950' : 'text-rose-600')}>
              {formatMoney(health.monthly_avg_balance)}
            </p>
            {renderCollapsedContext()}
          </div>

          {isExpanded ? renderExpandedContent() : null}
        </Card>
      </div>
    </div>
  );
}
