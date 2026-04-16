'use client';

import { useMemo } from 'react';

import { Card } from '@/components/ui/card';
import { formatMoney } from '@/lib/utils/format';
import type { Transaction } from '@/types/transaction';

const MAX_MONTHS = 6;

type Props = {
  transactions: Transaction[];
  isLoading?: boolean;
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

function daysInMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
}

export function AvgDailyExpenseWidget({ transactions, isLoading = false }: Props) {
  const avgDailyExpense = useMemo(() => {
    const analyticsExpenses = transactions.filter(
      (transaction) => transaction.affects_analytics && transaction.type === 'expense' && transaction.operation_type !== 'credit_payment' && transaction.operation_type !== 'credit_early_repayment',
    );

    if (analyticsExpenses.length === 0) {
      return null;
    }

    const currentMonth = startOfMonth(new Date());
    const sortedExpenses = [...analyticsExpenses].sort(
      (left, right) => new Date(left.transaction_date).getTime() - new Date(right.transaction_date).getTime(),
    );
    const firstExpenseMonth = startOfMonth(new Date(sortedExpenses[0].transaction_date));
    const candidateStartMonth = shiftMonth(currentMonth, -(MAX_MONTHS - 1));
    const startMonth = firstExpenseMonth > candidateStartMonth ? firstExpenseMonth : candidateStartMonth;

    let totalExpense = 0;
    let totalDays = 0;
    const includedMonthKeys = new Set<string>();

    for (
      let cursor = new Date(startMonth.getFullYear(), startMonth.getMonth(), 1);
      cursor <= currentMonth;
      cursor = shiftMonth(cursor, 1)
    ) {
      totalDays += daysInMonth(cursor);
      includedMonthKeys.add(monthKey(cursor));
    }

    for (const transaction of analyticsExpenses) {
      const key = monthKey(new Date(transaction.transaction_date));
      if (!includedMonthKeys.has(key)) continue;
      totalExpense += Number(transaction.amount);
    }

    if (totalDays === 0) {
      return null;
    }

    return Math.round(totalExpense / totalDays);
  }, [transactions]);

  return (
    <Card className="p-4 lg:p-5">
      <h4 className="text-base font-semibold text-slate-900">Среднедневные траты</h4>
      <p className="mt-1 text-sm text-slate-500">Средний расход в день</p>

      <div className="mt-5">
        <p className="text-[32px] font-semibold tracking-tight text-slate-950">
          {isLoading ? '...' : avgDailyExpense === null ? 'Нет данных' : formatMoney(avgDailyExpense)}
        </p>
        <p className="mt-2 text-sm text-slate-500">за последние 6 месяцев</p>
      </div>
    </Card>
  );
}
