'use client';

import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { PiggyBank } from 'lucide-react';

import { AvgDailyExpenseWidget } from '@/components/dashboard/avg-daily-expense-widget';
import { AvailableFinancesWidget } from '@/components/dashboard/available-finances-widget';
import { DisciplineCard } from '@/components/dashboard/discipline-card';
import { DTICard } from '@/components/dashboard/dti-card';
import { FreeNetCapitalWidget } from '@/components/dashboard/free-net-capital-widget';
import { IncomeStructureWidget } from '@/components/dashboard/income-structure-widget';
import { MonthlyAvgBalanceCard } from '@/components/dashboard/monthly-avg-balance-card';
import { SafetyBufferWidget } from '@/components/dashboard/safety-buffer-widget';
import { SixMonthTrendChartCard } from '@/components/dashboard/six-month-trend-chart-card';
import { SixMonthTrendWidget } from '@/components/dashboard/six-month-trend-widget';
import { TopExpenseCategoriesWidget } from '@/components/dashboard/top-expense-categories-widget';
import { PageShell } from '@/components/layout/page-shell';
import { FinancialIndependenceWidget } from '@/components/planning/financial-independence-widget';
import { FiScoreWidget, FI_SCORE_WIDGET_EVENT } from '@/components/planning/fi-score-widget';
import { Card } from '@/components/ui/card';
import { ErrorState, LoadingState } from '@/components/states/page-state';
import { getAccounts } from '@/lib/api/accounts';
import { getCategories } from '@/lib/api/categories';
import { getCounterparties } from '@/lib/api/counterparties';
import { getGoals } from '@/lib/api/goals';
import { getTransactions } from '@/lib/api/transactions';
import { formatMoney } from '@/lib/utils/format';
import { useFinancialHealth } from '@/hooks/use-financial-health';

const today = new Date();

export default function DashboardPage() {
  const [activeCard, setActiveCard] = useState<string | null>(null);
  const healthQuery = useFinancialHealth();
  const health = healthQuery.data;
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'dashboard'], queryFn: () => getCategories() });
  const goalsQuery = useQuery({ queryKey: ['goals'], queryFn: getGoals });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const transactionsQuery = useQuery({ queryKey: ['transactions', 'dashboard-v2'], queryFn: () => getTransactions() });

  const isLoading =
    healthQuery.isLoading ||
    accountsQuery.isLoading ||
    categoriesQuery.isLoading ||
    goalsQuery.isLoading ||
    transactionsQuery.isLoading ||
    counterpartiesQuery.isLoading;

  const isError = Boolean(
    healthQuery.error ||
      accountsQuery.error ||
      categoriesQuery.error ||
      goalsQuery.error ||
      transactionsQuery.error ||
      counterpartiesQuery.error,
  );

  const stats = useMemo(() => {
    const transactions = transactionsQuery.data ?? [];
    const accounts = accountsQuery.data ?? [];
    const counterparties = counterpartiesQuery.data ?? [];

    const currentMonthTransactions = transactions.filter((transaction) => {
      const date = new Date(transaction.transaction_date);
      return date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth();
    });

    const totalBalance = accounts.reduce((sum, account) => sum + Number(account.balance), 0);
    const receivable = counterparties.reduce((sum, item) => sum + Number(item.receivable_amount), 0);
    const payable = counterparties.reduce((sum, item) => sum + Number(item.payable_amount), 0);
    const expense = currentMonthTransactions
      .filter((transaction) => transaction.type === 'expense' && transaction.affects_analytics)
      .reduce((sum, transaction) => sum + Number(transaction.amount), 0);

    return {
      expense,
      totalBalance,
      receivable,
      payable,
    };
  }, [accountsQuery.data, counterpartiesQuery.data, transactionsQuery.data]);

  useEffect(() => {
    function handleFiScoreWidget(event: Event) {
      const customEvent = event as CustomEvent<{ source?: string; open?: boolean }>;
      if (customEvent.detail?.source !== 'dashboard-card' && customEvent.detail?.open) {
        setActiveCard(null);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleFiScoreWidget as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleFiScoreWidget as EventListener);
  }, []);

  const toggle = (key: string) => {
    document.dispatchEvent(
      new CustomEvent(FI_SCORE_WIDGET_EVENT, {
        detail: { source: 'dashboard-card', open: true },
      }),
    );
    setActiveCard((current) => (current === key ? null : key));
  };

  return (
    <PageShell
      title="Дашборд"
      description="Ключевые финансовые показатели, динамика месяца, бюджет и долговая нагрузка в одном экране."
    >
      {isLoading ? (
        <LoadingState
          title="Собираем показатели"
          description="Подтягиваем транзакции, цели, бюджеты и финансовое здоровье."
        />
      ) : null}
      {isError ? (
        <ErrorState
          title="Не удалось загрузить дашборд"
          description="Проверь доступность backend API и повтори попытку."
        />
      ) : null}

      {!isLoading && !isError && health ? (
        <>
          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Основные показатели</h3>
              <p className="mt-1 text-sm text-slate-500">
                Сводка по финансовой устойчивости, долговой нагрузке и дисциплине.
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <FiScoreWidget data={healthQuery.data} isLoading={healthQuery.isLoading} />
              <FinancialIndependenceWidget data={healthQuery.data} isLoading={healthQuery.isLoading} />
              <DTICard health={health} isExpanded={activeCard === 'dti'} onToggle={() => toggle('dti')} />
              <DisciplineCard
                health={health}
                isExpanded={activeCard === 'discipline'}
                onToggle={() => toggle('discipline')}
              />
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Деньги месяца</h3>
              <p className="mt-1 text-sm text-slate-500">
                Текущая динамика доходов, расходов и качества накоплений.
              </p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <AvailableFinancesWidget accounts={accountsQuery.data ?? []} isLoading={accountsQuery.isLoading} />
              <FreeNetCapitalWidget
                accounts={accountsQuery.data ?? []}
                goals={goalsQuery.data ?? []}
                counterparties={counterpartiesQuery.data ?? []}
                transactions={transactionsQuery.data ?? []}
                isLoading={
                  accountsQuery.isLoading ||
                  goalsQuery.isLoading ||
                  counterpartiesQuery.isLoading ||
                  transactionsQuery.isLoading
                }
              />
              <SafetyBufferWidget goals={goalsQuery.data ?? []} isLoading={goalsQuery.isLoading} />
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Аналитика</h3>
              <p className="mt-1 text-sm text-slate-500">
                Динамика, структура расходов и ключевые аналитические показатели.
              </p>
            </div>
            <div className="grid gap-4 xl:grid-cols-[0.72fr_1.28fr] xl:items-start">
              <SixMonthTrendWidget
                transactions={transactionsQuery.data ?? []}
                isLoading={transactionsQuery.isLoading}
              />
              <SixMonthTrendChartCard
                transactions={transactionsQuery.data ?? []}
                isLoading={transactionsQuery.isLoading}
              />
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
              <AvgDailyExpenseWidget
                transactions={transactionsQuery.data ?? []}
                isLoading={transactionsQuery.isLoading}
              />
            </div>
          </section>

          <section className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Капитал и долги</h3>
              <p className="mt-1 text-sm text-slate-500">Средний остаток и текущий долг по обязательствам.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-2">
              <MonthlyAvgBalanceCard
                monthlyAvgBalance={health.monthly_avg_balance}
                monthsCalculated={health.months_calculated}
                goals={goalsQuery.data ?? []}
                isExpanded={activeCard === 'avgBalance'}
                onToggle={() => toggle('avgBalance')}
              />
              <Card className="p-5 lg:p-6">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-500">Долги</p>
                    <div className="mt-3 flex items-center gap-3 text-2xl font-semibold text-slate-950 lg:text-3xl">
                      <PiggyBank className="size-5 text-sky-500" />
                      {formatMoney(stats.payable + health.leverage_total_debt)}
                    </div>
                    <p className="mt-2 text-sm text-slate-500">
                      Сумма кредитной задолженности и обязательств перед контрагентами.
                    </p>
                  </div>
                </div>
                <div className="mt-4 grid gap-2 text-sm text-slate-600">
                  <div className="rounded-2xl bg-slate-50 p-3">
                    Кредиты: <span className="font-medium text-slate-900">{formatMoney(health.leverage_total_debt)}</span>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-3">
                    Я должен: <span className="font-medium text-slate-900">{formatMoney(stats.payable)}</span>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-3">
                    Мне должны: <span className="font-medium text-slate-900">{formatMoney(stats.receivable)}</span>
                  </div>
                  <div className="rounded-2xl bg-slate-50 p-3">
                    Текущий капитал: <span className="font-medium text-slate-900">{formatMoney(stats.totalBalance)}</span>
                  </div>
                </div>
              </Card>
            </div>
          </section>
        </>
      ) : null}
    </PageShell>
  );
}