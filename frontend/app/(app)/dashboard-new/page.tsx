'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, LoadingState } from '@/components/states/page-state';
import { SectionMoney } from '@/components/dashboard-new/section-money';
import { SectionAnalytics } from '@/components/dashboard-new/section-analytics';
import { SectionCapital } from '@/components/dashboard-new/section-capital';
import {
  computeFlow,
  computeLoad,
  computeReserve,
  computeAvailableFinances,
  computeMonthProgress,
  computeSafetyBuffer,
  computeTrend,
  computeTopExpenses,
  computeExpenseTotals,
  computeIncomeStructure,
  computeAvgDailyExpense,
  computeCapital,
  computeDebts,
  computeInstallments,
  getTransactionYears,
  getTransactionMonths,
  toNum,
} from '@/components/dashboard-new/dashboard-data';
import type { FlowType } from '@/components/dashboard-new/dashboard-data';
import { getAccounts } from '@/lib/api/accounts';
import { getBudgetProgress } from '@/lib/api/budget';
import { getCategories } from '@/lib/api/categories';
import { getCounterparties } from '@/lib/api/counterparties';
import { getGoals } from '@/lib/api/goals';
import { getRealAssets } from '@/lib/api/real-assets';
import { getTransactions } from '@/lib/api/transactions';
import { useFinancialHealth } from '@/hooks/use-financial-health';

export default function DashboardNewPage() {
  const currentDate = new Date();
  const currentMonth = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, '0')}-01`;

  const healthQuery = useFinancialHealth();
  const health = healthQuery.data;
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const budgetQuery = useQuery({
    queryKey: ['budget', currentMonth],
    queryFn: () => getBudgetProgress(currentMonth),
  });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'dashboard-new'], queryFn: () => getCategories() });
  const goalsQuery = useQuery({ queryKey: ['goals'], queryFn: getGoals });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const realAssetsQuery = useQuery({ queryKey: ['real-assets'], queryFn: getRealAssets });
  const transactionsQuery = useQuery({ queryKey: ['transactions', 'dashboard-new'], queryFn: () => getTransactions() });

  const isLoading =
    healthQuery.isLoading ||
    accountsQuery.isLoading ||
    budgetQuery.isLoading ||
    categoriesQuery.isLoading ||
    goalsQuery.isLoading ||
    counterpartiesQuery.isLoading ||
    realAssetsQuery.isLoading ||
    transactionsQuery.isLoading;

  const isError = Boolean(
    healthQuery.error ||
      accountsQuery.error ||
      budgetQuery.error ||
      categoriesQuery.error ||
      goalsQuery.error ||
      counterpartiesQuery.error ||
      realAssetsQuery.error ||
      transactionsQuery.error,
  );

  const accounts = accountsQuery.data ?? [];
  const transactions = transactionsQuery.data ?? [];
  const categories = categoriesQuery.data ?? [];
  const goals = goalsQuery.data ?? [];
  const counterparties = counterpartiesQuery.data ?? [];
  const realAssets = realAssetsQuery.data ?? [];
  const budget = budgetQuery.data ?? [];

  // ── Trend controls ──────────────────────────────────────────────

  const now = new Date();
  const [trendYear, setTrendYear] = useState(now.getFullYear());
  const [trendMonth, setTrendMonth] = useState(now.getMonth());
  const [flowType, setFlowType] = useState<FlowType>('full');

  const trendYears = useMemo(() => {
    const years = getTransactionYears(transactions);
    const cy = now.getFullYear();
    if (!years.includes(cy)) years.unshift(cy);
    return years;
  }, [transactions]);

  const availableMonths = useMemo(() => {
    const months = getTransactionMonths(transactions, trendYear);
    // Always include current month for the current year
    const cy = now.getFullYear();
    const cm = now.getMonth();
    if (trendYear === cy && !months.includes(cm)) months.push(cm);
    months.sort((a, b) => a - b);
    return months.length > 0 ? months : [now.getMonth()];
  }, [transactions, trendYear]);

  // Snap trendMonth to an available month when year changes
  useEffect(() => {
    if (availableMonths.length > 0 && !availableMonths.includes(trendMonth)) {
      setTrendMonth(availableMonths[availableMonths.length - 1]);
    }
  }, [availableMonths, trendMonth]);

  const installmentCardIds = useMemo(
    () => new Set(accounts.filter((a) => a.account_type === 'installment_card').map((a) => a.id)),
    [accounts],
  );

  // ── Computed data ───────────────────────────────────────────────

  const flow = useMemo(() => (health ? computeFlow(transactions) : null), [transactions, health]);
  const load = useMemo(() => (health ? computeLoad(health) : null), [health]);
  const reserve = useMemo(() => (health ? computeReserve(goals, health) : null), [goals, health]);

  const availableFinances = useMemo(() => computeAvailableFinances(accounts), [accounts]);
  const monthProgress = useMemo(() => computeMonthProgress(budget), [budget]);
  const safetyBuffer = useMemo(() => (health ? computeSafetyBuffer(goals, health) : null), [goals, health]);

  const trendMonthsCount = useMemo(() => {
    // Find earliest transaction to determine how many months to show
    let earliest: string | null = null;
    for (const tx of transactions) {
      if (tx.affects_analytics && (!earliest || tx.transaction_date < earliest)) {
        earliest = tx.transaction_date;
      }
    }
    if (!earliest) return 6;
    const earlyYear = parseInt(earliest.slice(0, 4), 10);
    const earlyMonth = parseInt(earliest.slice(5, 7), 10) - 1;
    const total = (trendYear - earlyYear) * 12 + (trendMonth - earlyMonth) + 1;
    return Math.max(total, 1);
  }, [transactions, trendYear, trendMonth]);

  const trend = useMemo(
    () =>
      computeTrend(transactions, {
        endYear: trendYear,
        endMonth: trendMonth,
        months: trendMonthsCount,
        flowType,
        installmentCardIds,
      }),
    [transactions, trendYear, trendMonth, trendMonthsCount, flowType, installmentCardIds],
  );
  const topExpenses = useMemo(() => computeTopExpenses(transactions, categories), [transactions, categories]);
  const totalExpenses = useMemo(() => computeExpenseTotals(transactions), [transactions]);
  const incomeStructure = useMemo(() => computeIncomeStructure(transactions, categories), [transactions, categories]);
  const avgDailyExpense = useMemo(() => computeAvgDailyExpense(transactions), [transactions]);

  const debtsData = useMemo(() => computeDebts(counterparties), [counterparties]);
  const capitalData = useMemo(
    () => (health ? computeCapital(accounts, realAssets, health, debtsData) : null),
    [accounts, realAssets, health, debtsData],
  );

  const installmentCards = useMemo(() => computeInstallments(transactions), [transactions]);

  return (
    <PageShell
      title="Дашборд"
      description="Ключевые финансовые показатели, динамика месяца, аналитика расходов и структура капитала."
    >
      {isLoading ? (
        <LoadingState
          title="Собираем показатели"
          description="Подтягиваем транзакции, цели, счета и данные финансового здоровья."
        />
      ) : null}
      {isError ? (
        <ErrorState
          title="Не удалось загрузить дашборд"
          description="Проверь доступность backend API и попробуй обновить страницу ещё раз."
        />
      ) : null}

      {!isLoading && !isError && health && flow && load && reserve && safetyBuffer && capitalData ? (
        <div className="space-y-6">
          <SectionMoney
            flow={flow}
            load={load}
            reserve={reserve}
            availableFinances={availableFinances}
            monthProgress={monthProgress}
            safetyBuffer={safetyBuffer}
          />

          <SectionAnalytics
            trend={trend}
            topExpenses={topExpenses}
            totalExpenses={totalExpenses}
            incomeStructure={incomeStructure}
            avgDailyExpense={avgDailyExpense}
            installmentCards={installmentCards}
            trendYears={trendYears}
            trendYear={trendYear}
            trendMonth={trendMonth}
            flowType={flowType}
            availableMonths={availableMonths}
            onTrendYearChange={setTrendYear}
            onTrendMonthChange={setTrendMonth}
            onFlowTypeChange={setFlowType}
          />

          <SectionCapital
            capital={capitalData}
            debts={debtsData}
            health={health}
          />
        </div>
      ) : null}
    </PageShell>
  );
}
