import type { BudgetProgress } from '@/types/budget';
import type { Transaction } from '@/types/transaction';

export type MonthProgressStatus = 'good' | 'warning' | 'danger' | 'no_data';

export type BarStatus = 'good' | 'warning' | 'danger';

export type ProgressBar = {
  label: string;
  spentAmount: number;
  plannedAmount: number;
  spentPercent: number;
  timePercent: number;
  status: BarStatus;
  topCategory: string | null;
};

export type MonthProgressMetrics = {
  daysPassed: number;
  daysTotal: number;
  timePercent: number;
  monthLabel: string;
  essential: ProgressBar;
  secondary: ProgressBar;
  status: MonthProgressStatus;
  hasData: boolean;
};

function getBarStatus(spentPercent: number, timePercent: number): BarStatus {
  const delta = spentPercent - timePercent;
  if (delta <= 5) return 'good';
  if (delta <= 20) return 'warning';
  return 'danger';
}

function getTopOverrunCategory(items: BudgetProgress[]): string | null {
  const overrun = items
    .filter((b) => Number(b.planned_amount) > 0 && Number(b.spent_amount) > Number(b.planned_amount))
    .sort(
      (a, b) =>
        (Number(b.spent_amount) - Number(b.planned_amount)) -
        (Number(a.spent_amount) - Number(a.planned_amount)),
    );
  return overrun[0]?.category_name ?? null;
}

function buildBar(
  items: BudgetProgress[],
  transactions: Transaction[],
  priority: string,
  timePercent: number,
  currentMonthKey: string,
): ProgressBar {
  const budgetItems = items.filter(
    (b) =>
      b.category_priority === priority &&
      b.category_kind === 'expense' &&
      !b.exclude_from_planning,
  );

  const plannedAmount = budgetItems.reduce((sum, b) => sum + Number(b.planned_amount), 0);

  const categoryIds = new Set(budgetItems.map((b) => b.category_id));
  const spentAmount = transactions
    .filter((tx) => {
      if (!tx.affects_analytics || tx.type !== 'expense') return false;
      if (tx.operation_type === 'credit_payment' || tx.operation_type === 'credit_early_repayment') return false;
      if (!tx.category_id || !categoryIds.has(tx.category_id)) return false;
      const txMonth = tx.transaction_date.slice(0, 7);
      return txMonth === currentMonthKey;
    })
    .reduce((sum, tx) => sum + Number(tx.amount ?? 0), 0);

  const spentPercent = plannedAmount > 0
    ? Math.round((spentAmount / plannedAmount) * 100)
    : 0;

  const label = priority === 'expense_essential' ? 'Обязательные' : 'Второстепенные';

  return {
    label,
    spentAmount,
    plannedAmount,
    spentPercent,
    timePercent,
    status: plannedAmount > 0 ? getBarStatus(spentPercent, timePercent) : 'good',
    topCategory: plannedAmount > 0 ? getTopOverrunCategory(budgetItems) : null,
  };
}

export function getMonthProgressMetrics(
  budgetProgress: BudgetProgress[],
  transactions: Transaction[],
): MonthProgressMetrics {
  const today = new Date();
  const daysTotal = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const daysPassed = today.getDate();
  const timePercent = Math.round((daysPassed / daysTotal) * 100);
  const monthLabel = today.toLocaleString('ru-RU', { month: 'long' });
  const currentMonthKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;

  const hasData = budgetProgress.length > 0 || transactions.length > 0;

  const essential = buildBar(
    budgetProgress, transactions, 'expense_essential', timePercent, currentMonthKey,
  );
  const secondary = buildBar(
    budgetProgress, transactions, 'expense_secondary', timePercent, currentMonthKey,
  );

  const worstStatus = (a: BarStatus, b: BarStatus): MonthProgressStatus => {
    if (a === 'danger' || b === 'danger') return 'danger';
    if (a === 'warning' || b === 'warning') return 'warning';
    if (!hasData) return 'no_data';
    return 'good';
  };

  return {
    daysPassed,
    daysTotal,
    timePercent,
    monthLabel,
    essential,
    secondary,
    status: worstStatus(essential.status, secondary.status),
    hasData,
  };
}
