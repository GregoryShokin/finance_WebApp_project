import type { Account } from '@/types/account';
import type { BudgetProgress } from '@/types/budget';
import type { Category } from '@/types/category';
import type { Counterparty } from '@/types/counterparty';
import type { FinancialHealth } from '@/types/financial-health';
import type { GoalWithProgress } from '@/types/goal';
import type { RealAsset } from '@/types/real-asset';
import type { Transaction } from '@/types/transaction';

// ── Helpers ──────────────────────────────────────────────────────

export function toNum(value: number | string | null | undefined) {
  return Number(value ?? 0);
}

export function formatRub(value: number) {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatPercent(value: number, decimals = 1) {
  return `${value.toFixed(decimals)}%`;
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function shiftMonth(base: Date, offset: number) {
  return new Date(base.getFullYear(), base.getMonth() + offset, 1);
}

function daysInMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
}

function mean(values: number[]) {
  if (values.length === 0) return 0;
  return values.reduce((s, v) => s + v, 0) / values.length;
}

/** Parse transaction_date reliably: use raw string slice to avoid timezone issues */
function txMonthKey(tx: Transaction) {
  const raw = tx.transaction_date;
  if (raw.length >= 7) {
    const y = raw.slice(0, 4);
    const m = raw.slice(5, 7);
    return `${y}-${m}`;
  }
  return monthKey(new Date(raw));
}

// ── Tag helpers ─────────────────────────────────────────────────

export type TagTone = 'green' | 'amber' | 'red' | 'blue' | 'slate';

export const TAG_CLASSES: Record<TagTone, string> = {
  green: 'bg-[#dcfce7] text-[#15803d]',
  amber: 'bg-[#fef3c7] text-[#b45309]',
  red: 'bg-[#fee2e2] text-[#dc2626]',
  blue: 'bg-[#dbeafe] text-[#2563eb]',
  slate: 'bg-[#f1f5f9] text-[#64748b]',
};

// ── Metrics (top row) ───────────────────────────────────────────

export type FlowMetric = { balance: number; label: string; tone: TagTone };
export type LoadMetric = { dti: number; label: string; tone: TagTone };
export type ReserveMetric = { months: number; label: string; tone: TagTone };

export function computeFlow(transactions: Transaction[]): FlowMetric {
  const now = new Date();
  const key = monthKey(now);
  let income = 0;
  let expense = 0;
  let creditPayments = 0;

  for (const tx of transactions) {
    if (!tx.affects_analytics) continue;
    if (txMonthKey(tx) !== key) continue;
    const amount = toNum(tx.amount);
    if (tx.type === 'income') income += amount;
    if (tx.type === 'expense') {
      if (tx.operation_type === 'credit_payment' || tx.operation_type === 'credit_early_repayment') {
        creditPayments += amount;
      } else {
        expense += amount;
      }
    }
  }

  const balance = income - expense - creditPayments;
  if (balance > 0) return { balance, label: 'В норме', tone: 'green' };
  if (balance > -5000) return { balance, label: 'Нормально', tone: 'amber' };
  return { balance, label: 'Плохо', tone: 'red' };
}

export function computeLoad(health: FinancialHealth): LoadMetric {
  const dti = health.dti;
  if (dti < 20) return { dti, label: 'Низкая', tone: 'green' };
  if (dti < 40) return { dti, label: 'Допустимая', tone: 'amber' };
  return { dti, label: 'Высокая', tone: 'red' };
}

export function computeReserve(
  goals: GoalWithProgress[],
  health: FinancialHealth,
): ReserveMetric {
  const bufferGoal = goals.find((g) => g.system_key === 'safety_buffer' && g.status === 'active');
  const saved = bufferGoal?.saved ?? 0;
  const avgExpense = health.avg_monthly_expenses ?? 0;
  const months = avgExpense > 0 ? saved / avgExpense : 0;

  if (months >= 3) return { months, label: 'Хороший', tone: 'green' };
  if (months >= 1) return { months, label: 'Минимальный', tone: 'amber' };
  return { months, label: 'Недостаточный', tone: 'red' };
}

// ── Available Finances ──────────────────────────────────────────

export type AvailableFinancesData = {
  total: number;
  debitAccounts: Array<{ id: number; name: string; balance: number; type: string }>;
  creditCards: Array<{ id: number; name: string; availableLimit: number; totalLimit: number; type: string }>;
  debitTotal: number;
  creditLimitTotal: number;
};

export function computeAvailableFinances(accounts: Account[]): AvailableFinancesData {
  const debitAccounts = accounts
    .filter(
      (a) =>
        a.account_type !== 'credit' &&
        a.account_type !== 'credit_card' &&
        a.account_type !== 'installment_card' &&
        a.account_type !== 'broker' &&
        a.account_type !== 'deposit',
    )
    .map((a) => ({
      id: a.id,
      name: a.name,
      balance: Math.max(0, toNum(a.balance)),
      type: a.account_type === 'cash' ? 'Кэш' : 'Дебетовая карта',
    }))
    .filter((a) => a.balance > 0);

  const creditCards = accounts
    .filter((a) => a.account_type === 'credit_card' || a.account_type === 'installment_card')
    .map((a) => {
      const limit = toNum(a.credit_limit_original);
      const balance = toNum(a.balance);
      const available = balance < 0 ? Math.max(0, limit - Math.abs(balance)) : Math.max(0, balance);
      return {
        id: a.id,
        name: a.name,
        availableLimit: available,
        totalLimit: limit,
        type: a.account_type === 'installment_card' ? 'Карта рассрочки' : 'Кредитная карта',
      };
    })
    .filter((c) => c.totalLimit > 0);

  const debitTotal = debitAccounts.reduce((s, a) => s + a.balance, 0);
  const creditLimitTotal = creditCards.reduce((s, c) => s + c.availableLimit, 0);

  return {
    total: debitTotal,
    debitAccounts,
    creditCards,
    debitTotal,
    creditLimitTotal,
  };
}

// ── Month Progress ──────────────────────────────────────────────

export type MonthProgressData = {
  essentialSpent: number;
  essentialPlanned: number;
  essentialPercent: number;
  essentialRemaining: number;
  secondarySpent: number;
  secondaryPlanned: number;
  secondaryPercent: number;
  secondaryRemaining: number;
  daysPassed: number;
  daysTotal: number;
  dayPercent: number;
  overallTone: TagTone;
  overallLabel: string;
  essentialCategories: Array<{ name: string; spent: number; planned: number }>;
  topOverspend: { name: string; overage: number } | null;
};

export function computeMonthProgress(budget: BudgetProgress[]): MonthProgressData {
  const now = new Date();
  const daysPassed = now.getDate();
  const daysTotal = daysInMonth(now);
  const dayPercent = Math.round((daysPassed / daysTotal) * 100);

  const essentialItems = budget.filter(
    (b) => b.category_kind === 'expense' && b.category_priority === 'expense_essential' && !b.exclude_from_planning,
  );
  const secondaryItems = budget.filter(
    (b) => b.category_kind === 'expense' && b.category_priority === 'expense_secondary' && !b.exclude_from_planning,
  );

  const essentialSpent = essentialItems.reduce((s, b) => s + b.spent_amount, 0);
  const essentialPlanned = essentialItems.reduce((s, b) => s + b.planned_amount, 0);
  const secondarySpent = secondaryItems.reduce((s, b) => s + b.spent_amount, 0);
  const secondaryPlanned = secondaryItems.reduce((s, b) => s + b.planned_amount, 0);

  const essentialPercent = essentialPlanned > 0 ? Math.round((essentialSpent / essentialPlanned) * 100) : 0;
  const secondaryPercent = secondaryPlanned > 0 ? Math.round((secondarySpent / secondaryPlanned) * 100) : 0;

  const essentialCategories = essentialItems
    .filter((b) => b.planned_amount > 0)
    .sort((a, b) => b.spent_amount - a.spent_amount)
    .slice(0, 4)
    .map((b) => ({ name: b.category_name, spent: b.spent_amount, planned: b.planned_amount }));

  let topOverspend: MonthProgressData['topOverspend'] = null;
  const allOverspent = [...essentialItems, ...secondaryItems]
    .filter((b) => b.spent_amount > b.planned_amount && b.planned_amount > 0)
    .sort((a, b) => (b.spent_amount - b.planned_amount) - (a.spent_amount - a.planned_amount));

  if (allOverspent.length > 0) {
    const top = allOverspent[0];
    topOverspend = { name: top.category_name, overage: top.spent_amount - top.planned_amount };
  }

  const maxPercent = Math.max(essentialPercent, secondaryPercent);
  let overallTone: TagTone = 'green';
  let overallLabel = 'В норме';
  if (maxPercent > dayPercent + 15) {
    overallTone = 'amber';
    overallLabel = 'Превышение';
  }
  if (maxPercent > dayPercent + 30) {
    overallTone = 'red';
    overallLabel = 'Перерасход';
  }

  return {
    essentialSpent,
    essentialPlanned,
    essentialPercent,
    essentialRemaining: Math.max(0, essentialPlanned - essentialSpent),
    secondarySpent,
    secondaryPlanned,
    secondaryPercent,
    secondaryRemaining: Math.max(0, secondaryPlanned - secondarySpent),
    daysPassed,
    daysTotal,
    dayPercent,
    overallTone,
    overallLabel,
    essentialCategories,
    topOverspend,
  };
}

// ── Safety Buffer ───────────────────────────────────────────────

export type SafetyBufferData = {
  saved: number;
  target: number;
  percent: number;
  avgExpense: number;
  coverageMonths: number;
};

export function computeSafetyBuffer(goals: GoalWithProgress[], health: FinancialHealth): SafetyBufferData {
  const bufferGoal = goals.find((g) => g.system_key === 'safety_buffer' && g.status === 'active');
  const saved = bufferGoal?.saved ?? 0;
  const target = bufferGoal?.target_amount ?? 0;
  const percent = target > 0 ? Math.round((saved / target) * 100) : 0;
  const avgExpense = health.avg_monthly_expenses ?? 0;
  const coverageMonths = avgExpense > 0 ? saved / avgExpense : 0;

  return { saved, target, percent, avgExpense, coverageMonths };
}

// ── Trend (parameterized) ────────────────────────────────────────

export type FlowType = 'basic' | 'full';

export type TrendPoint = {
  key: string;
  label: string;
  income: number;
  expense: number;
  creditPayments: number;
  balance: number;
};

export type TrendData = {
  points: TrendPoint[];
  avgIncome: number;
  avgExpense: number;
  avgCreditPayments: number;
  avgBalance: number;
};

export type TrendOptions = {
  endYear: number;
  endMonth: number; // 0-indexed (0=January)
  months?: number; // default 6
  flowType?: FlowType; // default 'full'
  installmentCardIds?: Set<number>;
};

export function computeTrend(
  transactions: Transaction[],
  options?: TrendOptions,
): TrendData | null {
  const now = new Date();
  const endYear = options?.endYear ?? now.getFullYear();
  const endMonth = options?.endMonth ?? now.getMonth();
  const MONTHS = options?.months ?? 6;
  const flowType = options?.flowType ?? 'full';
  const installmentCardIds = options?.installmentCardIds ?? new Set<number>();

  const analytics = transactions.filter((tx) => tx.affects_analytics);
  if (analytics.length === 0) return null;

  const monthLabels = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  const endMonthStart = new Date(endYear, endMonth, 1);

  const buckets = new Map<string, TrendPoint>();
  const order: string[] = [];

  for (let offset = MONTHS - 1; offset >= 0; offset -= 1) {
    const d = shiftMonth(endMonthStart, -offset);
    const key = monthKey(d);
    order.push(key);
    buckets.set(key, {
      key,
      label: monthLabels[d.getMonth()],
      income: 0,
      expense: 0,
      creditPayments: 0,
      balance: 0,
    });
  }

  for (const tx of analytics) {
    const key = txMonthKey(tx);
    const bucket = buckets.get(key);
    if (!bucket) continue;

    // Skip transfers and early repayments (both flows exclude these)
    if (tx.operation_type === 'transfer' || tx.operation_type === 'credit_early_repayment') continue;

    // For basic flow: only regular transactions
    if (flowType === 'basic' && !tx.is_regular) continue;

    const amount = toNum(tx.amount);

    if (tx.type === 'income') {
      bucket.income += amount;
    }
    if (tx.type === 'expense') {
      // Both flows: exclude installment card expenses
      if (installmentCardIds.has(tx.account_id)) continue;

      if (tx.operation_type === 'credit_payment') {
        bucket.creditPayments += amount;
      } else {
        bucket.expense += amount;
      }
    }
  }

  const points = order
    .map((k) => buckets.get(k)!)
    .map((p) => ({ ...p, balance: p.income - p.expense - p.creditPayments }));

  const endKey = monthKey(endMonthStart);
  const completed = points.filter((p) => p.key !== endKey && (p.income > 0 || p.expense > 0));
  // If no completed months but end month has data, still show
  const hasAnyData = points.some((p) => p.income > 0 || p.expense > 0 || p.creditPayments > 0);
  if (!hasAnyData) return null;

  const forAvg = completed.length > 0 ? completed : points.filter((p) => p.income > 0 || p.expense > 0);

  return {
    points,
    avgIncome: mean(forAvg.map((p) => p.income)),
    avgExpense: mean(forAvg.map((p) => p.expense)),
    avgCreditPayments: mean(forAvg.map((p) => p.creditPayments)),
    avgBalance: mean(forAvg.map((p) => p.balance)),
  };
}

/** Get the range of years present in the transaction data */
export function getTransactionYears(transactions: Transaction[]): number[] {
  const years = new Set<number>();
  for (const tx of transactions) {
    const y = parseInt(tx.transaction_date.slice(0, 4), 10);
    if (!isNaN(y)) years.add(y);
  }
  return [...years].sort((a, b) => b - a);
}

// ── Top Expense Categories ──────────────────────────────────────

export type CategoryStatus = 'spike' | 'drift' | 'normal';

export type TopExpenseItem = {
  name: string;
  amount: number;
  status: CategoryStatus;
  isRegular: boolean;
  avgAmount: number;
  deviation: number;
  monthsGrowing: number;
};

export function computeTopExpenses(
  transactions: Transaction[],
  categories: Category[],
): TopExpenseItem[] {
  const analytics = transactions.filter(
    (tx) =>
      tx.affects_analytics &&
      tx.type === 'expense' &&
      tx.operation_type !== 'credit_payment' &&
      tx.operation_type !== 'credit_early_repayment',
  );

  const categoriesById = new Map(categories.map((c) => [c.id, c]));
  const now = new Date();
  const currentYear = now.getFullYear();
  const currentMonth = now.getMonth();
  const currentKey = monthKey(now);

  // Group current month by category
  const grouped = new Map<string, { name: string; amount: number; categoryId: number | null; isRegular: boolean }>();

  for (const tx of analytics) {
    const d = new Date(tx.transaction_date);
    if (d.getFullYear() !== currentYear || d.getMonth() !== currentMonth) continue;
    const cat = tx.category_id ? categoriesById.get(tx.category_id) : undefined;
    const name = cat?.name ?? 'Без категории';
    const key = String(tx.category_id ?? 'uncategorized');
    const existing = grouped.get(key);
    if (existing) {
      existing.amount += toNum(tx.amount);
    } else {
      grouped.set(key, {
        name,
        amount: toNum(tx.amount),
        categoryId: tx.category_id,
        isRegular: cat?.regularity === 'regular',
      });
    }
  }

  const items = [...grouped.values()].sort((a, b) => b.amount - a.amount).slice(0, 5);

  // Detect anomalies
  return items.map((item) => {
    const historical: number[] = [];
    for (let offset = 1; offset <= 6; offset += 1) {
      const refDate = shiftMonth(new Date(currentYear, currentMonth, 1), -offset);
      const key = monthKey(refDate);
      const total = analytics
        .filter(
          (tx) =>
            (tx.category_id === item.categoryId || (item.categoryId === null && tx.category_id === null)) &&
            txMonthKey(tx) === key,
        )
        .reduce((s, tx) => s + toNum(tx.amount), 0);
      historical.push(total);
    }

    const nonZero = historical.filter((v) => v > 0);
    const avgAmount = nonZero.length > 0 ? nonZero.reduce((s, v) => s + v, 0) / nonZero.length : 0;

    const isSpike = avgAmount > 0 && item.amount > avgAmount * 1.25 && item.amount - avgAmount > 1500;
    if (isSpike) {
      return { ...item, status: 'spike' as const, avgAmount, deviation: item.amount - avgAmount, monthsGrowing: 0 };
    }

    let monthsGrowing = 0;
    for (let i = 0; i < historical.length - 1; i += 1) {
      if (historical[i] > historical[i + 1] && historical[i] > 0) monthsGrowing += 1;
      else break;
    }
    const baseAmount = historical[monthsGrowing] ?? 0;
    const isDrift = monthsGrowing >= 2 && baseAmount > 0 && historical[0] - baseAmount > 2000;
    if (isDrift) {
      return { ...item, status: 'drift' as const, avgAmount, deviation: item.amount - avgAmount, monthsGrowing };
    }

    return { ...item, status: 'normal' as const, avgAmount, deviation: item.amount - avgAmount, monthsGrowing: 0 };
  });
}

export function computeExpenseTotals(transactions: Transaction[]) {
  const now = new Date();
  const key = monthKey(now);
  let total = 0;

  for (const tx of transactions) {
    if (!tx.affects_analytics || tx.type !== 'expense') continue;
    if (tx.operation_type === 'credit_payment' || tx.operation_type === 'credit_early_repayment') continue;
    if (txMonthKey(tx) !== key) continue;
    total += toNum(tx.amount);
  }

  return total;
}

// ── Income / Expense Structure ──────────────────────────────────

export type IncomeSource = { name: string; amount: number };

export type IncomeStructureData = {
  sources: IncomeSource[];
  totalIncome: number;
  essentialShare: number;
  secondaryShare: number;
  balanceShare: number;
  // Expense structure for collapsed view
  essentialSpent: number;
  secondarySpent: number;
  balanceRemaining: number;
};

export function computeIncomeStructure(
  transactions: Transaction[],
  categories: Category[],
): IncomeStructureData | null {
  const analytics = transactions.filter((tx) => tx.affects_analytics);
  if (analytics.length === 0) return null;

  const categoriesById = new Map(categories.map((c) => [c.id, c]));
  const now = new Date();
  const MAX_MONTHS = 6;

  // Collect completed months
  const monthBuckets: Array<{ income: number; essential: number; secondary: number }> = [];

  for (let offset = 1; offset <= MAX_MONTHS; offset += 1) {
    const d = shiftMonth(now, -offset);
    const key = monthKey(d);
    let income = 0;
    let essential = 0;
    let secondary = 0;

    for (const tx of analytics) {
      if (txMonthKey(tx) !== key) continue;
      const amount = toNum(tx.amount);
      if (tx.type === 'income') { income += amount; continue; }
      if (tx.type !== 'expense') continue;
      if (tx.operation_type === 'credit_payment' || tx.operation_type === 'credit_early_repayment') continue;
      const priority = categoriesById.get(tx.category_id ?? -1)?.priority ?? tx.category_priority ?? null;
      if (priority === 'expense_essential') essential += amount;
      else secondary += amount;
    }

    if (income > 0 || essential > 0 || secondary > 0) {
      monthBuckets.push({ income, essential, secondary });
    }
  }

  if (monthBuckets.length === 0) return null;

  const avgIncome = mean(monthBuckets.map((b) => b.income));
  if (avgIncome <= 0) return null;

  const avgEssential = mean(monthBuckets.map((b) => b.essential));
  const avgSecondary = mean(monthBuckets.map((b) => b.secondary));
  const avgBalance = avgIncome - avgEssential - avgSecondary;

  // Income sources for current month
  const currentKey = monthKey(now);
  const incomeByCategory = new Map<string, { name: string; amount: number }>();

  let curEssential = 0;
  let curSecondary = 0;
  let curIncome = 0;

  for (const tx of analytics) {
    if (txMonthKey(tx) !== currentKey) continue;
    const amount = toNum(tx.amount);

    if (tx.type === 'income') {
      curIncome += amount;
      const cat = tx.category_id ? categoriesById.get(tx.category_id) : undefined;
      const name = cat?.name ?? 'Прочие доходы';
      const key = String(tx.category_id ?? 'other');
      const existing = incomeByCategory.get(key);
      if (existing) existing.amount += amount;
      else incomeByCategory.set(key, { name, amount });
    }

    if (tx.type === 'expense') {
      if (tx.operation_type === 'credit_payment' || tx.operation_type === 'credit_early_repayment') continue;
      const priority = categoriesById.get(tx.category_id ?? -1)?.priority ?? tx.category_priority ?? null;
      if (priority === 'expense_essential') curEssential += amount;
      else curSecondary += amount;
    }
  }

  const sources = [...incomeByCategory.values()].sort((a, b) => b.amount - a.amount);

  return {
    sources,
    totalIncome: avgIncome,
    essentialShare: (avgEssential / avgIncome) * 100,
    secondaryShare: (avgSecondary / avgIncome) * 100,
    balanceShare: (avgBalance / avgIncome) * 100,
    essentialSpent: curEssential,
    secondarySpent: curSecondary,
    balanceRemaining: Math.max(0, curIncome - curEssential - curSecondary),
  };
}

// ── Avg Daily Expense ───────────────────────────────────────────

export function computeAvgDailyExpense(transactions: Transaction[]) {
  const analytics = transactions.filter(
    (tx) =>
      tx.affects_analytics &&
      tx.type === 'expense' &&
      tx.operation_type !== 'credit_payment' &&
      tx.operation_type !== 'credit_early_repayment',
  );

  const now = new Date();
  const thirtyDaysAgo = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 30);
  let total = 0;
  let days = 0;

  for (const tx of analytics) {
    const d = new Date(tx.transaction_date);
    if (d >= thirtyDaysAgo && d <= now) {
      total += toNum(tx.amount);
    }
  }

  days = 30;
  return days > 0 ? total / days : 0;
}

// ── Capital ─────────────────────────────────────────────────────

export type CapitalData = {
  liquidTotal: number;
  depositTotal: number;
  brokerTotal: number;
  realAssetsTotal: number;
  totalAssets: number;
  totalDebt: number;
  liquidCapital: number;
  netCapital: number;
  accounts: Account[];
  realAssets: RealAsset[];
  creditAccounts: Array<{ name: string; balance: number; rate: number | null; remaining: number | null }>;
  creditCards: Array<{ name: string; used: number; limit: number; utilization: number }>;
};

export function computeCapital(
  accounts: Account[],
  realAssets: RealAsset[],
  health: FinancialHealth,
): CapitalData {
  const liquid = accounts.filter(
    (a) =>
      a.account_type !== 'credit' &&
      a.account_type !== 'credit_card' &&
      a.account_type !== 'broker' &&
      a.account_type !== 'deposit' &&
      a.account_type !== 'installment_card',
  );
  const deposits = accounts.filter((a) => a.account_type === 'deposit');
  const brokers = accounts.filter((a) => a.account_type === 'broker');

  const liquidTotal = liquid.reduce((s, a) => s + Math.max(0, toNum(a.balance)), 0);
  const depositTotal = deposits.reduce((s, a) => s + Math.max(0, toNum(a.balance)), 0);
  const brokerTotal = brokers.reduce((s, a) => s + Math.max(0, toNum(a.balance)), 0);
  const realAssetsTotal = realAssets.reduce((s, a) => s + Math.max(0, toNum(a.estimated_value)), 0);
  const totalAssets = liquidTotal + depositTotal + brokerTotal + realAssetsTotal;
  const totalDebt = health.leverage_total_debt;
  const liquidCapital = liquidTotal + depositTotal - totalDebt;
  const netCapital = totalAssets - totalDebt;

  const creditAccounts = accounts
    .filter((a) => a.account_type === 'credit')
    .map((a) => ({
      name: a.name,
      balance: Math.abs(toNum(a.balance)),
      rate: a.credit_interest_rate != null ? toNum(a.credit_interest_rate) : null,
      remaining: a.credit_term_remaining ?? null,
    }));

  const creditCards = accounts
    .filter((a) => a.account_type === 'credit_card' || a.account_type === 'installment_card')
    .map((a) => {
      const limit = toNum(a.credit_limit_original);
      const balance = toNum(a.balance);
      const used = a.credit_limit_original != null
        ? (balance < 0 ? Math.abs(balance) : Math.max(0, limit - balance))
        : 0;
      return { name: a.name, used, limit, utilization: limit > 0 ? (used / limit) * 100 : 0 };
    })
    .filter((c) => c.limit > 0);

  return {
    liquidTotal,
    depositTotal,
    brokerTotal,
    realAssetsTotal,
    totalAssets,
    totalDebt,
    liquidCapital,
    netCapital,
    accounts,
    realAssets,
    creditAccounts,
    creditCards,
  };
}

// ── Debts ───────────────────────────────────────────────────────

export type DebtsData = {
  receivableTotal: number;
  payableTotal: number;
  netPosition: number;
  receivables: Array<{ name: string; amount: number }>;
  payables: Array<{ name: string; amount: number }>;
};

export function computeDebts(counterparties: Counterparty[]): DebtsData {
  const receivables = counterparties
    .filter((c) => c.receivable_amount > 0)
    .map((c) => ({ name: c.name, amount: c.receivable_amount }));
  const payables = counterparties
    .filter((c) => c.payable_amount > 0)
    .map((c) => ({ name: c.name, amount: c.payable_amount }));

  const receivableTotal = receivables.reduce((s, r) => s + r.amount, 0);
  const payableTotal = payables.reduce((s, p) => s + p.amount, 0);

  return {
    receivableTotal,
    payableTotal,
    netPosition: receivableTotal - payableTotal,
    receivables,
    payables,
  };
}
