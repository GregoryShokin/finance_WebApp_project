'use client';

import { useQuery } from '@tanstack/react-query';

import { AvgDailyExpenseWidget } from '@/components/dashboard/avg-daily-expense-widget';
import { AvailableFinancesWidget } from '@/components/dashboard/available-finances-widget';
import { BudgetPaceWidget } from '@/components/dashboard/budget-pace-widget';
import { CapitalWidget } from '@/components/dashboard/capital-widget';
import { CreditsWidget } from '@/components/dashboard/credits-widget';
import { DebtsWidget } from '@/components/dashboard/debts-widget';
import { IncomeStructureWidget } from '@/components/dashboard/income-structure-widget';
import { MonthlyAvgBalanceCard } from '@/components/dashboard/monthly-avg-balance-card';
import { SafetyBufferWidget } from '@/components/dashboard/safety-buffer-widget';
import { SixMonthTrendChartCard } from '@/components/dashboard/six-month-trend-chart-card';
import { SixMonthTrendWidget } from '@/components/dashboard/six-month-trend-widget';
import { TopExpenseCategoriesWidget } from '@/components/dashboard/top-expense-categories-widget';
import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, LoadingState } from '@/components/states/page-state';
import { getAccounts } from '@/lib/api/accounts';
import { getBudgetProgress } from '@/lib/api/budget';
import { getCategories } from '@/lib/api/categories';
import { getCounterparties } from '@/lib/api/counterparties';
import { getGoals } from '@/lib/api/goals';
import { getLargePurchases } from '@/lib/api/analytics';
import { getRealAssets } from '@/lib/api/real-assets';
import { getTransactions } from '@/lib/api/transactions';
import { useFinancialHealth } from '@/hooks/use-financial-health';

export default function DashboardPage() {
  const currentDate = new Date();
  const currentMonth = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, '0')}-01`;
  const healthQuery = useFinancialHealth();
  const health = healthQuery.data;
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const budgetQuery = useQuery({
    queryKey: ['budget', currentMonth],
    queryFn: () => getBudgetProgress(currentMonth),
  });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'dashboard'], queryFn: () => getCategories() });
  const goalsQuery = useQuery({ queryKey: ['goals'], queryFn: getGoals });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const realAssetsQuery = useQuery({ queryKey: ['real-assets'], queryFn: getRealAssets });
  const transactionsQuery = useQuery({ queryKey: ['transactions', 'dashboard-v2'], queryFn: () => getTransactions() });
  const largePurchasesQuery = useQuery({ queryKey: ['large-purchases', 6], queryFn: () => getLargePurchases(6), staleTime: 1000 * 60 * 5 });

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

  return (
    <PageShell
      title="Дашборд"
      description="Ключевые финансовые показатели, динамика месяца, аналитика расходов и структура капитала в одном экране."
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

      {!isLoading && !isError && health ? (
        <>
          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Деньги месяца</h3>
              <p className="mt-1 text-sm text-slate-500">Текущая динамика доходов, расходов и качества накоплений.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <AvailableFinancesWidget accounts={accountsQuery.data ?? []} isLoading={accountsQuery.isLoading} />
              <MonthlyAvgBalanceCard
                health={health}
                transactions={transactionsQuery.data ?? []}
                categories={categoriesQuery.data ?? []}
                goals={goalsQuery.data ?? []}
              />
              <BudgetPaceWidget />
              <SafetyBufferWidget goals={goalsQuery.data ?? []} isLoading={goalsQuery.isLoading} largePurchasesTotal={largePurchasesQuery.data?.total_amount ? Number(largePurchasesQuery.data.total_amount) : 0} />
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Аналитика</h3>
              <p className="mt-1 text-sm text-slate-500">Динамика, структура расходов и ключевые аналитические показатели.</p>
            </div>
            <div className="grid gap-4 xl:grid-cols-[0.72fr_1.28fr] xl:items-start">
              <SixMonthTrendWidget transactions={transactionsQuery.data ?? []} isLoading={transactionsQuery.isLoading} />
              <SixMonthTrendChartCard transactions={transactionsQuery.data ?? []} isLoading={transactionsQuery.isLoading} />
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 xl:items-start">
              <IncomeStructureWidget
                transactions={transactionsQuery.data ?? []}
                categories={categoriesQuery.data ?? []}
                isLoading={transactionsQuery.isLoading || categoriesQuery.isLoading}
              />
              <TopExpenseCategoriesWidget
                transactions={transactionsQuery.data ?? []}
                categories={categoriesQuery.data ?? []}
                isLoading={transactionsQuery.isLoading || categoriesQuery.isLoading}
              />
              <AvgDailyExpenseWidget transactions={transactionsQuery.data ?? []} isLoading={transactionsQuery.isLoading} />
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Капитал и долги</h3>
              <p className="mt-1 text-sm text-slate-500">Структура активов, обязательств и кредитной нагрузки.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <CapitalWidget
                accounts={accountsQuery.data ?? []}
                realAssets={realAssetsQuery.data ?? []}
                health={health}
                isLoading={accountsQuery.isLoading || realAssetsQuery.isLoading}
              />
              <DebtsWidget
                counterparties={counterpartiesQuery.data ?? []}
                health={health}
                isLoading={counterpartiesQuery.isLoading}
              />
              <CreditsWidget
                accounts={accountsQuery.data ?? []}
                transactions={transactionsQuery.data ?? []}
                health={health}
                isLoading={accountsQuery.isLoading || transactionsQuery.isLoading}
              />
            </div>
          </section>
        </>
      ) : null}
    </PageShell>
  );
}
