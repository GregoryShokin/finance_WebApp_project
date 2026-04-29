import type { Account } from '@/types/account';
import type { BudgetProgress } from '@/types/budget';
import type { Category } from '@/types/category';
import type { DebtPartner } from '@/types/debt-partner';
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

export type FlowMetric = { balance: number; label: string; tone: TagTone; monthsCount?: number };
export type LoadMetric = { dti: number; label: string; tone: TagTone };
export type ReserveMetric = { months: number; label: string; tone: TagTone };
export type BufferMetric = { months: number; label: string; tone: TagTone };

// Phase 6: metrics cards driven by /metrics/summary (single source of truth).
import type { MetricsSummary } from '@/lib/api/metrics';

export function computeFlowFromSummary(summary: MetricsSummary): FlowMetric {
  const { basic_flow, zone } = summary.flow;
  const label = zone === 'healthy' ? 'В норме' : zone === 'tight' ? 'Впритык' : 'Дефицит';
  const tone: TagTone = zone === 'healthy' ? 'green' : zone === 'tight' ? 'amber' : 'red';
  return { balance: basic_flow, label, tone };
}

/**
 * Average monthly flow over the last 12 months (including current month).
 * Only months that contain at least one transaction count — empty months
 * (before first activity and gaps in between) are excluded from the denominator.
 *
 * Badge reflects the averaged value of the selected flow type:
 *   - basic: lifestyle share (avg basic / avg regular income) — ≥20% healthy, ≥0% tight, <0 deficit
 *   - free/full: sign of the averaged value — >0 healthy, =0 tight, <0 deficit
 */
export function computeAverageFlow(
  summary: MetricsSummary,
  transactions: Transaction[],
  ccAccountIds: Set<number>,
  flowType: 'basic' | 'free' | 'full',
): FlowMetric {
  // Any transaction makes the month "active" — empty months are excluded.
  const activeMonths = new Set<string>();
  for (const tx of transactions) {
    activeMonths.add(txMonthKey(tx));
  }

  const now = new Date();
  const windowKeys: Array<{ year: number; month: number; key: string }> = [];
  for (let i = 11; i >= 0; i--) {
    const d = shiftMonth(new Date(now.getFullYear(), now.getMonth(), 1), -i);
    windowKeys.push({ year: d.getFullYear(), month: d.getMonth(), key: monthKey(d) });
  }

  const values: number[] = [];
  const regularIncomes: number[] = [];
  for (const { year, month, key } of windowKeys) {
    if (!activeMonths.has(key)) continue;
    const m = computeFlowForPeriod(transactions, year, month, ccAccountIds);
    const v = flowType === 'basic' ? m.basicFlow : flowType === 'free' ? m.freeCapital : m.fullFlow;
    values.push(v);
    // regularIncome is computed inside computeFlowForPeriod but not returned — recompute cheaply via breakdown
    const b = computeFlowBreakdown(transactions, { year, month });
    regularIncomes.push(b.regularIncome);
  }

  const avg = values.length > 0 ? mean(values) : 0;

  // Badge: depends on flow type
  let label: string;
  let tone: TagTone;
  if (values.length === 0) {
    label = '—';
    tone = 'slate';
  } else if (flowType === 'basic') {
    const avgIncome = mean(regularIncomes);
    const share = avgIncome > 0 ? (avg / avgIncome) * 100 : avg >= 0 ? 0 : -1;
    if (share >= 20) { label = 'В норме'; tone = 'green'; }
    else if (share >= 0) { label = 'Впритык'; tone = 'amber'; }
    else { label = 'Дефицит'; tone = 'red'; }
  } else {
    if (avg > 0) { label = 'В норме'; tone = 'green'; }
    else if (avg === 0) { label = 'Впритык'; tone = 'amber'; }
    else { label = 'Дефицит'; tone = 'red'; }
  }

  return { balance: avg, label, tone, monthsCount: values.length };
}

export function computeLoadFromSummary(summary: MetricsSummary): LoadMetric {
  const dti = summary.dti.dti_percent ?? 0;
  const zone = summary.dti.zone;
  const label = zone === 'normal' ? 'Низкая' : zone === 'acceptable' ? 'Допустимая' : zone === 'danger' ? 'Высокая' : zone === 'critical' ? 'Критическая' : '—';
  const tone: TagTone = zone === 'normal' ? 'green' : zone === 'acceptable' ? 'amber' : 'red';
  return { dti, label, tone };
}

export function computeBufferFromSummary(summary: MetricsSummary): BufferMetric {
  const months = summary.buffer_stability.months ?? 0;
  const zone = summary.buffer_stability.zone;
  const label =
    zone === 'excellent' ? 'Отличный'
    : zone === 'normal' ? 'Хороший'
    : zone === 'minimum' ? 'Минимальный'
    : 'Недостаточный';
  const tone: TagTone =
    zone === 'excellent' || zone === 'normal' ? 'green'
    : zone === 'minimum' ? 'amber'
    : 'red';
  return { months, label, tone };
}

// Phase 5: detailed breakdown for three-layer FlowWidget.
// Main aggregates (basic_flow, free_capital, full_flow) come from /metrics/summary;
// this breakdown provides segment values (regular vs all) that API doesn't expose.
export interface FlowBreakdown {
  regularIncome: number;
  regularExpenses: number;
  allIncome: number;
  allExpenses: number;
  investmentBuy: number;
  creditDisbursement: number;
}

export function computeFlowBreakdown(
  transactions: Transaction[],
  options?: { year?: number; month?: number },
): FlowBreakdown {
  const now = new Date();
  const targetYear = options?.year ?? now.getFullYear();
  const targetMonth = options?.month ?? now.getMonth();
  const key = monthKey(new Date(targetYear, targetMonth, 1));

  let regularIncome = 0;
  let regularExpenses = 0;
  let allIncome = 0;
  let allExpenses = 0;
  let investmentBuy = 0;
  let creditDisbursement = 0;

  for (const tx of transactions) {
    if (txMonthKey(tx) !== key) continue;
    const amount = toNum(tx.amount);

    // Credit disbursement: physical cash inflow when loan lands on liquid account.
    // Marked affects_analytics=False on backend, so we scan it separately before that filter.
    if (tx.type === 'income' && tx.operation_type === 'credit_disbursement') {
      creditDisbursement += amount;
      continue;
    }

    if (!tx.affects_analytics) continue;

    if (tx.type === 'income') {
      allIncome += amount;
      if (tx.is_regular) regularIncome += amount;
    }
    if (
      tx.type === 'expense'
      && tx.operation_type !== 'transfer'
      && tx.operation_type !== 'credit_early_repayment'
    ) {
      allExpenses += amount;
      if (tx.is_regular) regularExpenses += amount;
    }
    if (tx.operation_type === 'investment_buy') {
      investmentBuy += amount;
    }
  }

  return { regularIncome, regularExpenses, allIncome, allExpenses, investmentBuy, creditDisbursement };
}

/**
 * Compute flow metrics (basic, free, full + aux) for any given period from raw transactions.
 * Used by FlowWidget when user picks a non-current month (API /metrics/summary only returns current).
 *
 * Precision note: `creditBodyPayments` here is summed from transfers with credit_account_id set,
 * which matches the backend definition for body payments but excludes the "monthly_payment × body_ratio"
 * approximation used by backend for free_capital. So values may differ slightly from summary endpoint.
 */
export interface FlowPeriodMetrics {
  basicFlow: number;
  freeCapital: number;
  // fullFlow = Δ liquid cash:
  //   + allIncome + creditDisbursement
  //   − allExpenses
  //   − creditBody                    (loan body payment from liquid → credit loan account)
  //   + ccCompensator                 (purchase on CC didn't drain liquid cash)
  //   − ccRepayment                   (transfer from liquid → CC to pay off the card)
  //   − earlyRepayment                (credit_early_repayment from liquid account)
  fullFlow: number;
  creditBody: number;
  ccCompensator: number;
  ccRepayment: number;
  earlyRepayment: number;
  lifestyleCurrent: number | null; // current-month basicFlow / regularIncome × 100
}

export function computeFlowForPeriod(
  transactions: Transaction[],
  year: number,
  month: number,
  ccAccountIds?: Set<number>,
): FlowPeriodMetrics {
  const key = monthKey(new Date(year, month, 1));
  let regularIncome = 0;
  let regularExpenses = 0;
  let allIncome = 0;
  let allExpenses = 0;
  let creditBody = 0;
  let creditDisbursement = 0;
  let ccCompensator = 0;
  let ccRepayment = 0; // transfer from liquid → CC account (outflow that fullFlow must reflect)
  let earlyRepayment = 0; // credit_early_repayment — outflow from liquid account

  for (const tx of transactions) {
    if (txMonthKey(tx) !== key) continue;
    const amount = toNum(tx.amount);

    // Transfers: skip from income/expense, but track:
    //   - credit body (transfer to credit loan account, flagged with credit_account_id)
    //   - CC repayment (transfer from liquid account to credit card / installment card)
    if (tx.operation_type === 'transfer') {
      if (tx.credit_account_id) {
        creditBody += amount;
      } else if (
        ccAccountIds
        && tx.target_account_id != null
        && ccAccountIds.has(tx.target_account_id)
        && !ccAccountIds.has(tx.account_id)
      ) {
        ccRepayment += amount;
      }
      continue;
    }
    // Early repayment: real outflow from liquid account (account_id is the source).
    // We assume account_id is liquid — safe, because early repayments by design debit a liquid source.
    if (tx.operation_type === 'credit_early_repayment') {
      earlyRepayment += amount;
      continue;
    }

    if (tx.type === 'income') {
      if (tx.operation_type === 'credit_disbursement') {
        creditDisbursement += amount;
      } else {
        allIncome += amount;
        if (tx.is_regular) regularIncome += amount;
      }
      continue;
    }
    if (tx.type === 'expense') {
      allExpenses += amount;
      if (tx.is_regular) regularExpenses += amount;
      // CC compensator: expense from a CC account (purchase didn't reduce liquid cash)
      if (ccAccountIds && ccAccountIds.has(tx.account_id)) {
        ccCompensator += amount;
      }
    }
  }

  const basicFlow = regularIncome - regularExpenses;
  const freeCapital = basicFlow - creditBody;
  const fullFlow =
    allIncome + creditDisbursement
    - allExpenses
    - creditBody
    + ccCompensator
    - ccRepayment
    - earlyRepayment;
  const lifestyleCurrent = regularIncome > 0 ? (basicFlow / regularIncome) * 100 : null;

  return {
    basicFlow,
    freeCapital,
    fullFlow,
    creditBody,
    ccCompensator,
    ccRepayment,
    earlyRepayment,
    lifestyleCurrent: lifestyleCurrent !== null ? Math.round(lifestyleCurrent * 10) / 10 : null,
  };
}

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
      if (tx.operation_type === 'credit_early_repayment') {
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
        a.account_type !== 'loan' &&
        a.account_type !== 'credit_card' &&
        a.account_type !== 'installment_card' &&
        a.account_type !== 'broker' &&
        a.account_type !== 'savings',
    )
    .map((a) => ({
      id: a.id,
      name: a.name,
      balance: Math.max(0, toNum(a.balance)),
      type: a.account_type === 'main' ? 'Кэш' : 'Дебетовая карта',
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

  const essentialSpent = essentialItems.reduce((s, b) => s + Number(b.spent_amount), 0);
  const essentialPlanned = essentialItems.reduce((s, b) => s + Number(b.planned_amount), 0);
  const secondarySpent = secondaryItems.reduce((s, b) => s + Number(b.spent_amount), 0);
  const secondaryPlanned = secondaryItems.reduce((s, b) => s + Number(b.planned_amount), 0);

  const essentialPercent = essentialPlanned > 0 ? Math.round((essentialSpent / essentialPlanned) * 100) : 0;
  const secondaryPercent = secondaryPlanned > 0 ? Math.round((secondarySpent / secondaryPlanned) * 100) : 0;

  const essentialCategories = essentialItems
    .filter((b) => Number(b.planned_amount) > 0)
    .sort((a, b) => Number(b.spent_amount) - Number(a.spent_amount))
    .slice(0, 4)
    .map((b) => ({ name: b.category_name, spent: Number(b.spent_amount), planned: Number(b.planned_amount) }));

  let topOverspend: MonthProgressData['topOverspend'] = null;
  const allOverspent = [...essentialItems, ...secondaryItems]
    .filter((b) => Number(b.spent_amount) > Number(b.planned_amount) && Number(b.planned_amount) > 0)
    .sort((a, b) => (Number(b.spent_amount) - Number(b.planned_amount)) - (Number(a.spent_amount) - Number(a.planned_amount)));

  if (allOverspent.length > 0) {
    const top = allOverspent[0];
    topOverspend = { name: top.category_name, overage: Number(top.spent_amount) - Number(top.planned_amount) };
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

export type FlowType = 'basic' | 'free' | 'full';

export type TrendBreakdown = {
  activeRegular: number;
  activeIrregular: number;
  passiveRegular: number;
  passiveIrregular: number;
};

export type ExpenseBreakdown = {
  essentialRegular: number;
  essentialIrregular: number;
  secondaryRegular: number;
  secondaryIrregular: number;
};

export type TrendPoint = {
  key: string;
  label: string;
  income: number;
  expense: number;
  creditPayments: number;
  balance: number;
  incomeBreakdown: TrendBreakdown;
  expenseBreakdown: ExpenseBreakdown;
};

export type TrendData = {
  points: TrendPoint[];
  /** Data for the specific selected month (end month) */
  selected: TrendPoint;
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
      incomeBreakdown: { activeRegular: 0, activeIrregular: 0, passiveRegular: 0, passiveIrregular: 0 },
      expenseBreakdown: { essentialRegular: 0, essentialIrregular: 0, secondaryRegular: 0, secondaryIrregular: 0 },
    });
  }

  for (const tx of analytics) {
    const key = txMonthKey(tx);
    const bucket = buckets.get(key);
    if (!bucket) continue;

    // Skip transfers and early repayments (income/expense counting excludes these)
    if (tx.operation_type === 'transfer' || tx.operation_type === 'credit_early_repayment') continue;

    // Basic/Free flow: only regular transactions. Full: all.
    if ((flowType === 'basic' || flowType === 'free') && !tx.is_regular) continue;

    const amount = toNum(tx.amount);

    if (tx.type === 'income') {
      bucket.income += amount;
      const priority = tx.category_priority;
      const isPassive = priority === 'income_passive';
      if (isPassive) {
        if (tx.is_regular) bucket.incomeBreakdown.passiveRegular += amount;
        else bucket.incomeBreakdown.passiveIrregular += amount;
      } else {
        if (tx.is_regular) bucket.incomeBreakdown.activeRegular += amount;
        else bucket.incomeBreakdown.activeIrregular += amount;
      }
    }
    if (tx.type === 'expense') {
      bucket.expense += amount;
      const priority = tx.category_priority;
      const isEssential = priority === 'expense_essential';
      if (isEssential) {
        if (tx.is_regular) bucket.expenseBreakdown.essentialRegular += amount;
        else bucket.expenseBreakdown.essentialIrregular += amount;
      } else {
        if (tx.is_regular) bucket.expenseBreakdown.secondaryRegular += amount;
        else bucket.expenseBreakdown.secondaryIrregular += amount;
      }
    }
  }

  // For 'free' flow: subtract credit body payments (transfers with credit_account_id set).
  // Transfers have affects_analytics=False on the backend, so scan raw transactions, not `analytics`.
  if (flowType === 'free') {
    for (const tx of transactions) {
      if (tx.operation_type !== 'transfer') continue;
      if (!tx.credit_account_id) continue;
      const bucket = buckets.get(txMonthKey(tx));
      if (!bucket) continue;
      bucket.creditPayments += toNum(tx.amount);
    }
  }

  const points = order
    .map((k) => buckets.get(k)!)
    .map((p): TrendPoint => ({ ...p, balance: p.income - p.expense - p.creditPayments }));

  const endKey = monthKey(endMonthStart);
  const completed = points.filter((p) => p.key !== endKey && (p.income > 0 || p.expense > 0));
  // If no completed months but end month has data, still show
  const hasAnyData = points.some((p) => p.income > 0 || p.expense > 0 || p.creditPayments > 0);
  if (!hasAnyData) return null;

  const forAvg = completed.length > 0 ? completed : points.filter((p) => p.income > 0 || p.expense > 0);

  const selected = points.find((p) => p.key === endKey) ?? points[points.length - 1];

  return {
    points,
    selected,
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

/** Get 0-indexed months that have transaction data for the given year */
export function getTransactionMonths(transactions: Transaction[], year: number): number[] {
  const months = new Set<number>();
  const prefix = String(year);
  for (const tx of transactions) {
    if (!tx.transaction_date.startsWith(prefix)) continue;
    const m = parseInt(tx.transaction_date.slice(5, 7), 10);
    if (!isNaN(m)) months.add(m - 1); // 0-indexed
  }
  return [...months].sort((a, b) => a - b);
}

// ── Top Expense Categories ──────────────────────────────────────

export type CategoryStatus = 'spike' | 'drift' | 'normal';

export type TopExpenseItem = {
  name: string;
  amount: number;
  status: CategoryStatus;
  isRegular: boolean;
  priority: string | null;
  avgAmount: number;
  deviation: number;
  monthsGrowing: number;
};

export function computeTopExpenses(
  transactions: Transaction[],
  categories: Category[],
  targetYear?: number,
  targetMonth?: number,
  limit = 5,
): TopExpenseItem[] {
  const analytics = transactions.filter(
    (tx) =>
      tx.affects_analytics &&
      tx.type === 'expense' &&
      
      tx.operation_type !== 'credit_early_repayment',
  );

  const categoriesById = new Map(categories.map((c) => [c.id, c]));
  const now = new Date();
  const currentYear = targetYear ?? now.getFullYear();
  const currentMonth = targetMonth ?? now.getMonth();

  // Group current month by category
  const grouped = new Map<string, { name: string; amount: number; categoryId: number | null; isRegular: boolean; priority: string | null }>();

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
        priority: cat?.priority ?? null,
      });
    }
  }

  const items = [...grouped.values()].sort((a, b) => b.amount - a.amount).slice(0, limit);

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

export function computeExpenseTotals(transactions: Transaction[], targetYear?: number, targetMonth?: number) {
  const now = new Date();
  const y = targetYear ?? now.getFullYear();
  const m = targetMonth ?? now.getMonth();
  const key = monthKey(new Date(y, m, 1));
  let total = 0;

  for (const tx of transactions) {
    if (!tx.affects_analytics || tx.type !== 'expense') continue;
    if (tx.operation_type === 'credit_early_repayment') continue;
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
      if (tx.operation_type === 'credit_early_repayment') continue;
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
      if (tx.operation_type === 'credit_early_repayment') continue;
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
  receivableTotal: number;
  totalAssets: number;
  creditDebt: number;
  creditCardDebt: number;
  counterpartyDebt: number;
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
  debts?: DebtsData,
): CapitalData {
  const liquid = accounts.filter(
    (a) =>
      a.account_type !== 'loan' &&
      a.account_type !== 'credit_card' &&
      a.account_type !== 'broker' &&
      a.account_type !== 'savings' &&
      a.account_type !== 'installment_card',
  );
  const deposits = accounts.filter((a) => a.account_type === 'savings');
  const brokers = accounts.filter((a) => a.account_type === 'broker');

  const liquidTotal = liquid.reduce((s, a) => s + Math.max(0, toNum(a.balance)), 0);
  const depositTotal = deposits.reduce((s, a) => s + Math.max(0, toNum(a.balance)), 0);
  const brokerTotal = brokers.reduce((s, a) => s + Math.max(0, toNum(a.balance)), 0);
  const realAssetsTotal = realAssets.reduce((s, a) => s + Math.max(0, toNum(a.estimated_value)), 0);
  const receivableTotal = toNum(debts?.receivableTotal);
  const counterpartyDebt = toNum(debts?.payableTotal);
  const totalAssets = liquidTotal + depositTotal + brokerTotal + realAssetsTotal + receivableTotal;
  const creditAccounts = accounts
    .filter((a) => a.account_type === 'loan')
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

  const creditCardDebt = creditCards.reduce((s, c) => s + c.used, 0);
  const creditDebt = toNum(health.leverage_total_debt);
  const totalDebt = creditDebt + creditCardDebt + counterpartyDebt;
  const liquidCapital = liquidTotal + depositTotal + receivableTotal - totalDebt;
  const netCapital = totalAssets - totalDebt;

  return {
    liquidTotal,
    depositTotal,
    brokerTotal,
    realAssetsTotal,
    receivableTotal,
    totalAssets,
    creditDebt,
    creditCardDebt,
    counterpartyDebt,
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

export function computeDebts(debtPartners: DebtPartner[]): DebtsData {
  const receivables = debtPartners
    .filter((c) => toNum(c.receivable_amount) > 0)
    .map((c) => ({ name: c.name, amount: toNum(c.receivable_amount) }));
  const payables = debtPartners
    .filter((c) => toNum(c.payable_amount) > 0)
    .map((c) => ({ name: c.name, amount: toNum(c.payable_amount) }));

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

// ── Installments (from transactions) ──────────────────────────

export type InstallmentItem = {
  name: string;
  monthlyPayment: number;
  remaining: number | null;
  totalAmount: number;
};

export function computeInstallments(transactions: Transaction[]): InstallmentItem[] {
  const now = new Date();
  return transactions
    .filter((tx) => tx.converted_to_installment && toNum(tx.installment_monthly_payment) > 0)
    .map((tx) => {
      const termMonths = tx.installment_term_months ?? 0;
      const txDate = new Date(tx.transaction_date);
      const monthsElapsed =
        (now.getFullYear() - txDate.getFullYear()) * 12 + (now.getMonth() - txDate.getMonth());
      const remaining = termMonths > 0 ? Math.max(0, termMonths - monthsElapsed) : null;
      return {
        name: tx.installment_description || tx.description || 'Рассрочка',
        monthlyPayment: toNum(tx.installment_monthly_payment),
        remaining,
        totalAmount: toNum(tx.amount),
      };
    })
    .filter((item) => item.remaining === null || item.remaining > 0);
}
