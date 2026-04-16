import type { Transaction } from '@/types/transaction';

export const MAX_MONTHS = 6;
export const VIEW_MODES = [
  { key: 'month', label: 'Выбор периода' },
  { key: 'average', label: 'Средние' },
] as const;
export const MONTH_OPTIONS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
export const TREND_COLORS = {
  pieIncome: '#14D8E1',
  pieExpense: '#E46363',
  pieCreditPayments: '#94A3B8',
  pieBalance: '#F59E0B',
  chartIncome: '#16A34A',
  chartExpense: '#EF4444',
  chartBalance: '#3B82F6',
};

export type ViewMode = (typeof VIEW_MODES)[number]['key'];

export type MonthlyPoint = {
  key: string;
  month: string;
  income: number;
  expense: number;
  creditPayments: number;
  balance: number;
  daysInMonth: number;
  year: number;
  monthIndex: number;
};

export type SummarySlice = {
  name: string;
  value: number;
  color: string;
  rawValue: number;
};

export type SummaryTotals = {
  income: number;
  expense: number;
  creditPayments: number;
  balance: number;
};

export type MonthOption = {
  key: string;
  label: string;
  year: number;
  monthIndex: number;
};

export type TrendMetrics = {
  chartData: MonthlyPoint[];
  avgMonthlyBalance: number;
  avgIncome: number;
  avgExpense: number;
  forecastMonthBalance: number;
  statusLabel: 'Хорошо' | 'Нормально' | 'Плохо';
  statusBadgeClass: string;
  summaryText: string;
  availableYears: number[];
  availableMonthOptions: MonthOption[];
  sixMonthAverageTotals: SummaryTotals;
};

export function parseMonthKey(key: string) {
  const [year, month] = key.split('-').map(Number);
  return {
    year,
    monthIndex: (month ?? 1) - 1,
  };
}

export function startOfMonth(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

export function shiftMonth(base: Date, offset: number) {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

export function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

export function daysInMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
}

function mean(values: number[]) {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getStatus(avgMonthlyBalance: number, forecastMonthBalance: number) {
  if (avgMonthlyBalance === 0) {
    if (forecastMonthBalance > 0) {
      return {
        statusLabel: 'Хорошо' as const,
        statusBadgeClass: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200',
      };
    }

    if (forecastMonthBalance < 0) {
      return {
        statusLabel: 'Плохо' as const,
        statusBadgeClass: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200',
      };
    }

    return {
      statusLabel: 'Нормально' as const,
      statusBadgeClass: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200',
    };
  }

  const tolerance = Math.abs(avgMonthlyBalance) * 0.1;
  if (forecastMonthBalance > avgMonthlyBalance + tolerance) {
    return {
      statusLabel: 'Хорошо' as const,
      statusBadgeClass: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200',
    };
  }

  if (forecastMonthBalance < avgMonthlyBalance - tolerance) {
    return {
      statusLabel: 'Плохо' as const,
      statusBadgeClass: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200',
    };
  }

  return {
    statusLabel: 'Нормально' as const,
    statusBadgeClass: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200',
  };
}

function buildSummaryText(avgMonthlyBalance: number, forecastMonthBalance: number) {
  const tolerance = Math.abs(avgMonthlyBalance) * 0.1;
  const delta = forecastMonthBalance - avgMonthlyBalance;

  if (delta > tolerance) return 'Прогноз заметно выше среднего значения';
  if (delta < -tolerance) return 'Прогноз заметно ниже среднего значения';
  return 'Прогноз близок к среднему значению';
}

export function buildTotals(income: number, expense: number, creditPayments = 0): SummaryTotals {
  return {
    income,
    expense,
    creditPayments,
    balance: income - expense - creditPayments,
  };
}

export function normalizeSlices(income: number, expense: number, creditPayments: number, balance: number): SummarySlice[] {
  return [
    { name: 'Доходы', value: Math.max(income, 0), color: TREND_COLORS.pieIncome, rawValue: income },
    { name: 'Расходы', value: Math.max(expense, 0), color: TREND_COLORS.pieExpense, rawValue: expense },
    { name: 'Кредиты', value: Math.max(creditPayments, 0), color: TREND_COLORS.pieCreditPayments, rawValue: creditPayments },
    { name: 'Остаток', value: Math.max(balance, 0), color: TREND_COLORS.pieBalance, rawValue: balance },
  ].filter((slice) => slice.value > 0 || slice.name === 'Остаток');
}

export function formatTrendYAxisValue(value: number) {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}м`;
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}к`;
  return String(Math.round(value));
}

export function getSixMonthTrendMetrics(transactions: Transaction[]): TrendMetrics | null {
  const analyticsTransactions = transactions.filter((transaction) => transaction.affects_analytics);
  if (analyticsTransactions.length === 0) return null;

  const today = new Date();
  const currentMonth = startOfMonth(today);
  const monthBuckets = new Map<string, MonthlyPoint>();
  const monthOrder: string[] = [];
  const years = new Set<number>();
  const sortedTransactions = [...analyticsTransactions].sort(
    (left, right) => new Date(left.transaction_date).getTime() - new Date(right.transaction_date).getTime(),
  );
  const firstTrackedDate = startOfMonth(new Date(sortedTransactions[0].transaction_date));
  const availableMonthOptions: MonthOption[] = [];

  for (
    let cursor = new Date(firstTrackedDate.getFullYear(), firstTrackedDate.getMonth(), 1);
    cursor <= currentMonth;
    cursor = shiftMonth(cursor, 1)
  ) {
    const key = monthKey(cursor);
    availableMonthOptions.push({
      key,
      label: `${MONTH_OPTIONS[cursor.getMonth()]} ${cursor.getFullYear()}`,
      year: cursor.getFullYear(),
      monthIndex: cursor.getMonth(),
    });
  }

  for (let offset = MAX_MONTHS - 1; offset >= 0; offset -= 1) {
    const pointDate = shiftMonth(currentMonth, -offset);
    const key = monthKey(pointDate);
    monthOrder.push(key);
    monthBuckets.set(key, {
      key,
      month: pointDate.toLocaleString('ru-RU', { month: 'short' }).replace('.', ''),
      income: 0,
      expense: 0,
      creditPayments: 0,
      balance: 0,
      daysInMonth: daysInMonth(pointDate),
      year: pointDate.getFullYear(),
      monthIndex: pointDate.getMonth(),
    });
  }

  for (const transaction of analyticsTransactions) {
    const transactionDate = new Date(transaction.transaction_date);
    const amount = Number(transaction.amount);
    const year = transactionDate.getFullYear();
    years.add(year);
    const currentKey = monthKey(transactionDate);
    const bucket = monthBuckets.get(currentKey);

    if (!bucket) continue;
    if (transaction.type === 'income') bucket.income += amount;
    if (transaction.type === 'expense' && transaction.operation_type !== 'credit_payment' && transaction.operation_type !== 'credit_early_repayment') bucket.expense += amount;
    if (transaction.operation_type === 'credit_payment' || transaction.operation_type === 'credit_early_repayment') bucket.creditPayments = (bucket.creditPayments ?? 0) + amount;
  }

  const chartData = monthOrder
    .map((key) => monthBuckets.get(key))
    .filter((bucket): bucket is MonthlyPoint => Boolean(bucket))
    .map((bucket) => ({ ...bucket, balance: bucket.income - bucket.expense - bucket.creditPayments }));

  const currentMonthKey = monthKey(currentMonth);
  const populatedMonths = chartData.filter(
    (point) => (point.income > 0 || point.expense > 0 || point.creditPayments > 0) && point.key !== currentMonthKey,
  );
  if (populatedMonths.length === 0) return null;

  const avgMonthlyBalance = mean(populatedMonths.map((point) => point.balance));
  const avgIncome = mean(populatedMonths.map((point) => point.income));
  const avgExpense = mean(populatedMonths.map((point) => point.expense));
  const avgCreditPayments = mean(populatedMonths.map((point) => point.creditPayments));
  const totalExpenses = populatedMonths.reduce((sum, point) => sum + point.expense, 0);
  const totalDays = populatedMonths.reduce((sum, point) => sum + point.daysInMonth, 0);
  const avgDailyExpense = totalDays > 0 ? totalExpenses / totalDays : 0;
  const forecastMonthExpense = avgDailyExpense * daysInMonth(currentMonth);
  const forecastMonthBalance = avgIncome - forecastMonthExpense - avgCreditPayments;
  const status = getStatus(avgMonthlyBalance, forecastMonthBalance);

  return {
    chartData,
    avgMonthlyBalance,
    avgIncome,
    avgExpense,
    forecastMonthBalance,
    statusLabel: status.statusLabel,
    statusBadgeClass: status.statusBadgeClass,
    summaryText: buildSummaryText(avgMonthlyBalance, forecastMonthBalance),
    availableYears: [...years].sort((a, b) => b - a),
    availableMonthOptions,
    sixMonthAverageTotals: {
      income: avgIncome,
      expense: avgExpense,
      creditPayments: avgCreditPayments,
      balance: avgMonthlyBalance,
    },
  };
}
