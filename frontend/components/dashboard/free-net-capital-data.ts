import type { Account } from '@/types/account';
import type { Counterparty } from '@/types/counterparty';
import type { GoalWithProgress } from '@/types/goal';
import type { Transaction } from '@/types/transaction';

export const FREE_NET_CAPITAL_MONTHS = 6;

export type FreeNetCapitalPoint = {
  key: string;
  month: string;
  value: number;
};

export type FreeNetCapitalMetrics = {
  personalAssets: number;
  targetAssets: number;
  debts: number;
  freeNetCapital: number;
  deltaFromPreviousMonth: number | null;
  chartData: FreeNetCapitalPoint[];
  messageLines: string[];
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

function getCreditCardLimit(account: Account) {
  return Number(account.credit_limit ?? account.credit_limit_original ?? 0);
}

function getPersonalAssets(accounts: Account[]) {
  return accounts.reduce((sum, account) => {
    const balance = Number(account.balance ?? 0);

    if (account.account_type === 'credit_card') {
      return sum + Math.max(0, balance - getCreditCardLimit(account));
    }

    if (account.account_type === 'credit' || account.is_credit) {
      return sum;
    }

    if (account.account_type === 'regular' || account.account_type === 'cash' || account.account_type === 'broker') {
      return sum + Math.max(0, balance);
    }

    return sum;
  }, 0);
}

function getCreditDebts(accounts: Account[]) {
  return accounts.reduce((sum, account) => {
    const balance = Number(account.balance ?? 0);

    if (account.account_type === 'credit_card') {
      return sum + Math.max(0, getCreditCardLimit(account) - balance);
    }

    if (account.account_type === 'credit' || account.is_credit) {
      return sum + Math.max(0, -balance);
    }

    return sum;
  }, 0);
}

function getTargetAssets(goals: GoalWithProgress[]) {
  return goals
    .filter((goal) => goal.status !== 'archived')
    .reduce((sum, goal) => sum + Number(goal.saved ?? 0), 0);
}

function getCounterpartyDebt(counterparties: Counterparty[]) {
  return counterparties.reduce((sum, item) => sum + Number(item.payable_amount ?? 0), 0);
}

function getFreeNetCapitalDelta(transaction: Transaction) {
  const amount = Number(transaction.amount ?? 0);

  if (transaction.goal_id) {
    return transaction.type === 'expense' ? -amount : amount;
  }

  switch (transaction.operation_type) {
    case 'transfer':
      return 0;
    case 'investment_buy':
      return 0;
    case 'investment_sell':
      return 0;
    case 'credit_disbursement':
      return 0;
    case 'credit_payment':
      return -Number(transaction.credit_interest_amount ?? 0);
    case 'debt':
      return 0;
    case 'refund':
      return amount;
    default:
      return transaction.type === 'income' ? amount : -amount;
  }
}

function buildMessageLines(freeNetCapital: number, targetAssets: number) {
  if (freeNetCapital > 0) {
    return [
      'Ситуация устойчивая: после вычета долгов у вас остаётся положительный объём свободных собственных средств.',
    ];
  }

  if (Math.abs(freeNetCapital) <= 10000) {
    return [
      'Запас минимален: свободных собственных средств почти не остаётся после вычета долгов.',
    ];
  }

  return [
    'Положение рискованное: свободных собственных средств недостаточно для покрытия долгов.',
    targetAssets >= Math.abs(freeNetCapital)
      ? 'С учётом денег, отложенных на цели, долговую нагрузку можно полностью перекрыть.'
      : 'Даже с учётом денег, отложенных на цели, долговая нагрузка остаётся выше доступных средств.',
  ];
}

export function getFreeNetCapitalMetrics(
  accounts: Account[],
  goals: GoalWithProgress[],
  counterparties: Counterparty[],
  transactions: Transaction[],
): FreeNetCapitalMetrics | null {
  const personalAssets = getPersonalAssets(accounts);
  const targetAssets = getTargetAssets(goals);
  const debts = getCreditDebts(accounts) + getCounterpartyDebt(counterparties);
  const freeNetCapital = personalAssets - targetAssets - debts;

  const sortedTransactions = [...transactions].sort(
    (left, right) => new Date(left.transaction_date).getTime() - new Date(right.transaction_date).getTime(),
  );

  const analyticsRelevantTransactions = sortedTransactions.filter((transaction) => {
    if (transaction.goal_id) return true;
    if (transaction.operation_type === 'credit_payment' || transaction.operation_type === 'credit_disbursement') return true;
    if (transaction.operation_type === 'debt') return true;
    return transaction.affects_analytics;
  });

  const currentMonth = startOfMonth(new Date());
  const monthOrder: Date[] = [];
  for (let offset = FREE_NET_CAPITAL_MONTHS - 1; offset >= 0; offset -= 1) {
    monthOrder.push(shiftMonth(currentMonth, -offset));
  }

  const monthDelta = new Map<string, number>();
  for (const pointDate of monthOrder) {
    monthDelta.set(monthKey(pointDate), 0);
  }

  for (const transaction of analyticsRelevantTransactions) {
    const key = monthKey(new Date(transaction.transaction_date));
    if (!monthDelta.has(key)) continue;
    monthDelta.set(key, (monthDelta.get(key) ?? 0) + getFreeNetCapitalDelta(transaction));
  }

  const chartDataDesc: FreeNetCapitalPoint[] = [];
  let rollingValue = freeNetCapital;

  for (let index = monthOrder.length - 1; index >= 0; index -= 1) {
    const pointDate = monthOrder[index];
    const key = monthKey(pointDate);
    chartDataDesc.push({
      key,
      month: pointDate.toLocaleString('ru-RU', { month: 'short' }).replace('.', ''),
      value: rollingValue,
    });
    rollingValue -= monthDelta.get(key) ?? 0;
  }

  const chartData = [...chartDataDesc].reverse();
  const previousMonthPoint = chartData.length >= 2 ? chartData[chartData.length - 2] : null;
  const deltaFromPreviousMonth = previousMonthPoint ? freeNetCapital - previousMonthPoint.value : null;

  return {
    personalAssets,
    targetAssets,
    debts,
    freeNetCapital,
    deltaFromPreviousMonth,
    chartData,
    messageLines: buildMessageLines(freeNetCapital, targetAssets),
  };
}
