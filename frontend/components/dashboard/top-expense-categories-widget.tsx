'use client';

import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TooltipProps } from 'recharts';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { Category, CategoryPriority } from '@/types/category';
import type { Transaction } from '@/types/transaction';

const MONTH_OPTIONS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const CATEGORY_TYPE_OPTIONS = [
  { key: 'essential', label: 'Обязательные' },
  { key: 'secondary', label: 'Второстепенные' },
] as const;

type CategoryType = (typeof CATEGORY_TYPE_OPTIONS)[number]['key'];

type Props = {
  transactions: Transaction[];
  categories: Category[];
  isLoading?: boolean;
};

type ExpenseItem = {
  categoryId: number | null;
  name: string;
  amount: number;
  priority: CategoryPriority | null;
};

type CategoryStatus = 'spike' | 'drift' | 'normal';

type ExpenseItemWithStatus = ExpenseItem & {
  status: CategoryStatus;
  avgAmount: number;
  monthsGrowing: number;
  deviation: number;
};

type MonthOption = {
  key: string;
  year: number;
  monthIndex: number;
  label: string;
};

type Metrics = {
  topFiveCurrentMonth: ExpenseItemWithStatus[];
  availableYears: number[];
  monthOptions: MonthOption[];
  selectedPeriodItems: ExpenseItemWithStatus[];
};

const BAR_COLORS: Record<CategoryStatus, string> = {
  spike: '#E24B4A',
  drift: '#EF9F27',
  normal: '#378ADD',
};

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function shiftMonth(base: Date, offset: number) {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

function normalizeExpensePriority(priority: CategoryPriority | null | undefined): CategoryType {
  return priority === 'expense_essential' ? 'essential' : 'secondary';
}

function buildExpenseItems(
  transactions: Transaction[],
  categoriesById: Map<number, Category>,
  predicate: (transaction: Transaction) => boolean,
) {
  const grouped = new Map<string, ExpenseItem>();

  for (const transaction of transactions) {
    if (!predicate(transaction)) continue;

    const amount = Number(transaction.amount);
    const category = transaction.category_id ? categoriesById.get(transaction.category_id) : undefined;
    const priority = category?.priority ?? transaction.category_priority ?? null;
    const name = category?.name ?? 'Без категории';
    const key = `${transaction.category_id ?? 'uncategorized'}:${priority ?? 'unknown'}:${name}`;
    const current = grouped.get(key);

    if (current) {
      current.amount += amount;
      continue;
    }

    grouped.set(key, {
      categoryId: transaction.category_id,
      name,
      amount,
      priority,
    });
  }

  return [...grouped.values()].sort((left, right) => right.amount - left.amount);
}

function detectCategoryStatus(
  categoryId: number | null,
  currentMonthAmount: number,
  transactions: Transaction[],
  referenceMonthKey: string,
): { status: CategoryStatus; avgAmount: number; monthsGrowing: number } {
  const refDate = new Date(`${referenceMonthKey}-01`);
  const historicalAmounts: number[] = [];

  for (let offset = 1; offset <= 6; offset += 1) {
    const monthDate = shiftMonth(refDate, -offset);
    const key = monthKey(monthDate);
    const total = transactions
      .filter((tx) =>
        tx.affects_analytics &&
        tx.type === 'expense' &&
        (tx.category_id === categoryId || (categoryId === null && tx.category_id === null)) &&
        monthKey(new Date(tx.transaction_date)) === key,
      )
      .reduce((sum, tx) => sum + Number(tx.amount), 0);
    historicalAmounts.push(total);
  }

  const nonZero = historicalAmounts.filter((value) => value > 0);
  const avgAmount = nonZero.length > 0
    ? nonZero.reduce((sum, value) => sum + value, 0) / nonZero.length
    : 0;

  const isSpike =
    avgAmount > 0 &&
    currentMonthAmount > avgAmount * 1.25 &&
    currentMonthAmount - avgAmount > 1500;

  if (isSpike) {
    return { status: 'spike', avgAmount, monthsGrowing: 0 };
  }

  let monthsGrowing = 0;
  for (let index = 0; index < historicalAmounts.length - 1; index += 1) {
    if (historicalAmounts[index] > historicalAmounts[index + 1] && historicalAmounts[index] > 0) {
      monthsGrowing += 1;
    } else {
      break;
    }
  }

  const baseAmount = historicalAmounts[monthsGrowing] ?? 0;
  const isDrift =
    monthsGrowing >= 2 &&
    baseAmount > 0 &&
    historicalAmounts[0] - baseAmount > 2000;

  if (isDrift) {
    return { status: 'drift', avgAmount, monthsGrowing };
  }

  return { status: 'normal', avgAmount, monthsGrowing: 0 };
}

function formatYAxisValue(value: number) {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}м`;
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}к`;
  return String(Math.round(value));
}

function renderTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;

  const item = payload[0]?.payload as ExpenseItemWithStatus | undefined;
  if (!item) return null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 py-2.5 shadow-lg">
      <p className="text-sm font-medium text-slate-900">{item.name}</p>
      <p className="mt-1 text-sm text-slate-500">{formatMoney(item.amount)}</p>
      {item.status === 'spike' && item.avgAmount > 0 ? (
        <p className="mt-1 text-xs text-rose-600">
          ↑ Всплеск: +{formatMoney(item.deviation)} к среднему
        </p>
      ) : null}
      {item.status === 'drift' ? (
        <p className="mt-1 text-xs text-amber-600">
          ↗ Растёт {item.monthsGrowing} мес. подряд
        </p>
      ) : null}
      {item.status === 'normal' && item.avgAmount > 0 ? (
        <p className="mt-1 text-xs text-slate-400">
          Среднее: {formatMoney(item.avgAmount)}
        </p>
      ) : null}
    </div>
  );
}

export function TopExpenseCategoriesWidget({ transactions, categories, isLoading = false }: Props) {
  const [categoryType, setCategoryType] = useState<CategoryType>('essential');
  const [selectedYear, setSelectedYear] = useState<number>(new Date().getFullYear());
  const [selectedMonthKey, setSelectedMonthKey] = useState<string>('');

  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'top-expense-categories-widget', expandHeight: 600 });

  const metrics = useMemo<Metrics | null>(() => {
    const analyticsExpenses = transactions.filter(
      (transaction) => transaction.affects_analytics && transaction.type === 'expense',
    );
    if (analyticsExpenses.length === 0) return null;

    const categoriesById = new Map(categories.map((category) => [category.id, category]));
    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = today.getMonth();
    const sortedTransactions = [...analyticsExpenses].sort(
      (left, right) => new Date(left.transaction_date).getTime() - new Date(right.transaction_date).getTime(),
    );
    const firstDate = new Date(sortedTransactions[0].transaction_date);
    const firstMonth = new Date(firstDate.getFullYear(), firstDate.getMonth(), 1);
    const currentMonthDate = new Date(currentYear, currentMonth, 1);
    const monthOptions: MonthOption[] = [];
    const years = new Set<number>();

    for (
      let cursor = new Date(firstMonth.getFullYear(), firstMonth.getMonth(), 1);
      cursor <= currentMonthDate;
      cursor = shiftMonth(cursor, 1)
    ) {
      years.add(cursor.getFullYear());
      monthOptions.push({
        key: monthKey(cursor),
        year: cursor.getFullYear(),
        monthIndex: cursor.getMonth(),
        label: `${MONTH_OPTIONS[cursor.getMonth()]} ${cursor.getFullYear()}`,
      });
    }

    const currentMonthReferenceKey = monthKey(today);

    const topFiveCurrentMonth: ExpenseItemWithStatus[] = buildExpenseItems(
      analyticsExpenses,
      categoriesById,
      (transaction) => {
        const date = new Date(transaction.transaction_date);
        return date.getFullYear() === currentYear && date.getMonth() === currentMonth;
      },
    )
      .slice(0, 5)
      .map((item) => {
        const { status, avgAmount, monthsGrowing } = detectCategoryStatus(
          item.categoryId,
          item.amount,
          analyticsExpenses,
          currentMonthReferenceKey,
        );

        return {
          ...item,
          status,
          avgAmount,
          monthsGrowing,
          deviation: item.amount - avgAmount,
        };
      });

    const selectedPeriodItems: ExpenseItemWithStatus[] = buildExpenseItems(
      analyticsExpenses,
      categoriesById,
      (transaction) => {
        const date = new Date(transaction.transaction_date);
        const currentKey = monthKey(date);
        const priority = categoriesById.get(transaction.category_id ?? -1)?.priority ?? transaction.category_priority ?? null;
        return currentKey === selectedMonthKey && normalizeExpensePriority(priority) === categoryType;
      },
    ).map((item) => {
      const { status, avgAmount, monthsGrowing } = detectCategoryStatus(
        item.categoryId,
        item.amount,
        analyticsExpenses,
        selectedMonthKey,
      );

      return {
        ...item,
        status,
        avgAmount,
        monthsGrowing,
        deviation: item.amount - avgAmount,
      };
    });

    return {
      topFiveCurrentMonth,
      availableYears: [...years].sort((a, b) => b - a),
      monthOptions,
      selectedPeriodItems,
    };
  }, [transactions, categories, categoryType, selectedMonthKey]);

  useEffect(() => {
    if (!metrics || metrics.availableYears.length === 0) return;
    if (!metrics.availableYears.includes(selectedYear)) {
      setSelectedYear(metrics.availableYears[0]);
    }
  }, [metrics, selectedYear]);

  useEffect(() => {
    if (!metrics || metrics.monthOptions.length === 0) return;
    if (!selectedMonthKey || !metrics.monthOptions.some((option) => option.key === selectedMonthKey)) {
      setSelectedMonthKey(metrics.monthOptions[metrics.monthOptions.length - 1].key);
    }
  }, [metrics, selectedMonthKey]);

  useEffect(() => {
    if (!metrics || metrics.monthOptions.length === 0) return;

    const monthsForYear = metrics.monthOptions.filter((option) => option.year === selectedYear);
    if (monthsForYear.length === 0) return;

    const currentSelected = monthsForYear.find((option) => option.key === selectedMonthKey);
    if (!currentSelected) {
      setSelectedMonthKey(monthsForYear[monthsForYear.length - 1].key);
    }
  }, [metrics, selectedYear, selectedMonthKey]);

  const monthsForSelectedYear = (metrics?.monthOptions ?? []).filter((option) => option.year === selectedYear);

  function renderCollapsedList() {
    if (!metrics || metrics.topFiveCurrentMonth.length === 0) {
      return (
        <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
          В этом месяце пока нет аналитических расходов по категориям.
        </div>
      );
    }

    return (
      <div className="mt-4 space-y-3">
        {metrics.topFiveCurrentMonth.map((item, index) => (
          <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-4 py-3">
            <span className="truncate text-sm font-medium text-slate-900">{item.name}</span>
            <div className="flex shrink-0 items-center gap-1.5">
              {item.status !== 'normal' ? (
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ background: BAR_COLORS[item.status] }}
                />
              ) : null}
              <span className="text-sm font-semibold text-slate-600">{formatMoney(item.amount)}</span>
            </div>
          </div>
        ))}
      </div>
    );
  }

  function renderExpandedControls() {
    return (
      <div className="mt-4 space-y-3">
        <div className="inline-flex rounded-full bg-slate-100 p-1 text-xs text-slate-500">
          {CATEGORY_TYPE_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setCategoryType(option.key)}
              className={cn(
                'rounded-full px-3 py-1.5 transition',
                categoryType === option.key ? 'bg-white text-slate-900 shadow-sm' : 'hover:text-slate-700',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <label className="relative block">
            <select
              value={String(selectedYear)}
              onChange={(event) => setSelectedYear(Number(event.target.value))}
              className="h-9 w-full appearance-none rounded-2xl border border-slate-200 bg-slate-50 px-3 pr-8 text-xs text-slate-700 outline-none transition focus:border-slate-400"
            >
              {metrics?.availableYears.map((year) => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-slate-400">▼</span>
          </label>

          <label className="relative block">
            <select
              value={selectedMonthKey}
              onChange={(event) => setSelectedMonthKey(event.target.value)}
              className="h-9 w-full appearance-none rounded-2xl border border-slate-200 bg-slate-50 px-3 pr-8 text-xs text-slate-700 outline-none transition focus:border-slate-400"
            >
              {monthsForSelectedYear.map((option) => (
                <option key={option.key} value={option.key}>{MONTH_OPTIONS[option.monthIndex]}</option>
              ))}
            </select>
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-slate-400">▼</span>
          </label>
        </div>
      </div>
    );
  }

  function renderExpandedChart() {
    if (!metrics || metrics.selectedPeriodItems.length === 0) {
      return (
        <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-3 text-xs text-slate-500">
          Для выбранного периода и типа категорий данных пока нет.
        </div>
      );
    }

    return (
      <div className="mt-4 h-[220px] rounded-[20px] bg-slate-50/70 px-2 py-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={metrics.selectedPeriodItems} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke="#E2E8F0" strokeDasharray="3 3" />
            <XAxis
              dataKey="name"
              tickLine={false}
              axisLine={false}
              tick={{ fill: '#64748B', fontSize: 9 }}
              interval={0}
              angle={-20}
              textAnchor="end"
              height={48}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              tick={{ fill: '#94A3B8', fontSize: 9 }}
              tickFormatter={formatYAxisValue}
              width={36}
            />
            <Tooltip content={renderTooltip} cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }} />
            <Bar dataKey="amount" radius={[6, 6, 0, 0]} maxBarSize={32}>
              {metrics.selectedPeriodItems.map((item, index) => (
                <Cell key={`cell-${index}`} fill={BAR_COLORS[item.status]} />
              ))}
              <LabelList
                dataKey="amount"
                position="top"
                content={(props: { x?: number | string; y?: number | string; width?: number | string; value?: number | string; index?: number }) => {
                  const { x, y, width, value, index } = props;
                  const item = metrics.selectedPeriodItems[index as number];
                  if (!item || x == null || y == null || width == null || value == null) return null;

                  const icon = item.status === 'spike' ? '↑' : item.status === 'drift' ? '↗' : null;
                  const iconColor = item.status === 'spike' ? '#A32D2D' : '#854F0B';
                  const cx = Number(x) + Number(width) / 2;

                  return (
                    <g>
                      <text
                        x={cx}
                        y={Number(y) - (icon ? 14 : 4)}
                        textAnchor="middle"
                        fontSize={8}
                        fill="#64748B"
                      >
                        {formatMoney(Number(value))}
                      </text>
                      {icon ? (
                        <text
                          x={cx}
                          y={Number(y) - 4}
                          textAnchor="middle"
                          fontSize={9}
                          fontWeight="600"
                          fill={iconColor}
                        >
                          {icon}
                        </text>
                      ) : null}
                    </g>
                  );
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    );
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-sm font-semibold text-slate-900">Топ 5 категорий расходов</p>
          <p className="mt-1 text-sm text-slate-500">за текущий месяц</p>
          <div className="mt-4 space-y-3">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="h-11 animate-pulse rounded-2xl bg-slate-50" />
            ))}
          </div>
        </>
      );
    }

    if (!metrics) {
      return (
        <>
          <p className="text-sm font-semibold text-slate-900">Топ 5 категорий расходов</p>
          <p className="mt-1 text-sm text-slate-500">за текущий месяц</p>
          <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
            Недостаточно данных по расходам для построения аналитики.
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-sm font-semibold text-slate-900">
          {isExpanded ? 'Категории расходов' : 'Топ 5 категорий расходов'}
        </p>
        <p className="mt-1 text-sm text-slate-500">
          {isExpanded ? 'Анализ расходов по категориям' : 'за текущий месяц'}
        </p>
        {toggleButton}

        {isExpanded ? (
          <>
            {renderExpandedControls()}
            {renderExpandedChart()}
          </>
        ) : (
          renderCollapsedList()
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
