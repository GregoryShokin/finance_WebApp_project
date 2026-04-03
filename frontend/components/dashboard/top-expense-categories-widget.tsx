'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TooltipProps } from 'recharts';

import { FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
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

type MonthOption = {
  key: string;
  year: number;
  monthIndex: number;
  label: string;
};

type Metrics = {
  topFiveCurrentMonth: ExpenseItem[];
  availableYears: number[];
  monthOptions: MonthOption[];
  selectedPeriodItems: ExpenseItem[];
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

function formatYAxisValue(value: number) {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}м`;
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}к`;
  return String(Math.round(value));
}

function renderTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;

  const item = payload[0];
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 py-2 shadow-lg">
      <p className="text-sm font-medium text-slate-900">{String(item.payload?.name ?? 'Категория')}</p>
      <p className="mt-1 text-sm text-slate-500">{formatMoney(Number(item.value ?? 0))}</p>
    </div>
  );
}

export function TopExpenseCategoriesWidget({ transactions, categories, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);
  const [categoryType, setCategoryType] = useState<CategoryType>('essential');
  const [selectedYear, setSelectedYear] = useState<number>(new Date().getFullYear());
  const [selectedMonthKey, setSelectedMonthKey] = useState<string>('');

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
      if (customEvent.detail?.source !== 'top-expense-categories-widget' && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, []);

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

    const topFiveCurrentMonth = buildExpenseItems(
      analyticsExpenses,
      categoriesById,
      (transaction) => {
        const date = new Date(transaction.transaction_date);
        return date.getFullYear() === currentYear && date.getMonth() === currentMonth;
      },
    ).slice(0, 5);

    const selectedPeriodItems = buildExpenseItems(
      analyticsExpenses,
      categoriesById,
      (transaction) => {
        const date = new Date(transaction.transaction_date);
        const currentKey = monthKey(date);
        const priority = categoriesById.get(transaction.category_id ?? -1)?.priority ?? transaction.category_priority ?? null;
        return currentKey === selectedMonthKey && normalizeExpensePriority(priority) === categoryType;
      },
    );

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

  function handleToggle() {
    setIsExpanded((current) => {
      const next = !current;
      document.dispatchEvent(
        new CustomEvent(FI_SCORE_WIDGET_EVENT, {
          detail: { source: 'top-expense-categories-widget', open: next },
        }),
      );
      return next;
    });
  }

  function renderCollapsedList() {
    if (!metrics || metrics.topFiveCurrentMonth.length === 0) {
      return (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
          В этом месяце пока нет аналитических расходов по категориям.
        </div>
      );
    }

    return (
      <div className="mt-4 space-y-3">
        {metrics.topFiveCurrentMonth.map((item, index) => (
          <div key={`${item.name}-${index}`} className="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-4 py-3">
            <span className="truncate text-sm font-medium text-slate-900">{item.name}</span>
            <span className="shrink-0 text-sm font-semibold text-slate-600">{formatMoney(item.amount)}</span>
          </div>
        ))}
      </div>
    );
  }

  function renderExpandedChart() {
    if (!metrics || metrics.selectedPeriodItems.length === 0) {
      return (
        <div className="mt-5 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
          Для выбранного периода и типа категорий данных пока нет.
        </div>
      );
    }

    return (
      <div className="mt-5 h-[320px] rounded-[28px] bg-slate-50/70 px-3 py-4 sm:px-4">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={metrics.selectedPeriodItems} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke="#E2E8F0" strokeDasharray="3 3" />
            <XAxis
              dataKey="name"
              tickLine={false}
              axisLine={false}
              interval={0}
              height={72}
              tick={{ fill: '#64748B', fontSize: 11 }}
              angle={-24}
              textAnchor="end"
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              tick={{ fill: '#94A3B8', fontSize: 12 }}
              tickFormatter={formatYAxisValue}
              width={52}
            />
            <Tooltip content={renderTooltip} />
            <Bar dataKey="amount" radius={[10, 10, 0, 0]} maxBarSize={48}>
              {metrics.selectedPeriodItems.map((item, index) => (
                <Cell
                  key={`${item.name}-${index}`}
                  fill={categoryType === 'essential' ? '#3B82F6' : '#F59E0B'}
                />
              ))}
              <LabelList
                dataKey="amount"
                position="top"
                formatter={(value: number) => formatMoney(value)}
                style={{ fill: '#475569', fontSize: 11, fontWeight: 600 }}
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
          <div className="pr-10">
            <p className="text-sm font-semibold text-slate-900">Топ 5 категорий расходов</p>
            <p className="mt-1 text-sm text-slate-500">за текущий месяц</p>
          </div>
          <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
            Недостаточно данных по расходам для построения аналитики.
          </div>
        </>
      );
    }

    return (
      <>
        <div className="flex items-start justify-between gap-4">
          <div className="pr-4">
            <h4 className="text-base font-semibold text-slate-900">
              {isExpanded ? 'Категории расходов' : 'Топ 5 категорий расходов'}
            </h4>
            <p className="mt-1 text-sm text-slate-500">
              {isExpanded ? 'Анализ расходов по категориям' : 'за текущий месяц'}
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

        {!isExpanded ? (
          renderCollapsedList()
        ) : (
          <>
            <div className="mt-5 space-y-3">
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
                    className="h-10 w-full appearance-none rounded-2xl border border-slate-200 bg-slate-50 px-4 pr-9 text-sm text-slate-700 outline-none transition focus:border-slate-400"
                  >
                    {metrics.availableYears.map((year) => (
                      <option key={year} value={year}>{year}</option>
                    ))}
                  </select>
                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">▼</span>
                </label>

                <label className="relative block">
                  <select
                    value={selectedMonthKey}
                    onChange={(event) => setSelectedMonthKey(event.target.value)}
                    className="h-10 w-full appearance-none rounded-2xl border border-slate-200 bg-slate-50 px-4 pr-9 text-sm text-slate-700 outline-none transition focus:border-slate-400"
                  >
                    {monthsForSelectedYear.map((option) => (
                      <option key={option.key} value={option.key}>{MONTH_OPTIONS[option.monthIndex]}</option>
                    ))}
                  </select>
                  <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">▼</span>
                </label>
              </div>
            </div>

            {renderExpandedChart()}
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
            'relative overflow-visible transition-[width,transform,box-shadow] duration-300 ease-out',
            isExpanded
              ? 'absolute right-0 top-0 z-50 w-[min(760px,calc(100vw-2rem))] p-5 shadow-2xl lg:p-6 xl:w-[760px]'
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
