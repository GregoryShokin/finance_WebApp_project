"use client";

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownCircle, ArrowUpCircle, CreditCard, FolderTree, ListChecks, Wallet } from 'lucide-react';
import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, LoadingState } from '@/components/states/page-state';
import { StatCard } from '@/components/shared/stat-card';
import { Card } from '@/components/ui/card';
import { getAccounts } from '@/lib/api/accounts';
import { getCategories } from '@/lib/api/categories';
import { getTransactions } from '@/lib/api/transactions';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import { formatDateTime } from '@/lib/utils/format';

export default function DashboardPage() {
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'dashboard'], queryFn: () => getCategories() });
  const transactionsQuery = useQuery({ queryKey: ['transactions', 'dashboard'], queryFn: () => getTransactions() });

  const stats = useMemo(() => {
    const accounts = accountsQuery.data ?? [];
    const categories = categoriesQuery.data ?? [];
    const transactions = transactionsQuery.data ?? [];

    const totalBalance = accounts.reduce((sum, account) => sum + Number(account.balance), 0);
    const income = transactions.filter((item) => item.type === 'income' && item.affects_analytics).reduce((sum, item) => sum + Number(item.amount), 0);
    const expense = transactions.filter((item) => item.type === 'expense' && item.affects_analytics).reduce((sum, item) => sum + Number(item.amount), 0);
    const reviewCount = transactions.filter((item) => item.needs_review).length;
    const latestTransactions = [...transactions]
      .sort((a, b) => new Date(b.transaction_date).getTime() - new Date(a.transaction_date).getTime())
      .slice(0, 5);

    return {
      totalBalance,
      income,
      expense,
      reviewCount,
      accountsCount: accounts.length,
      activeAccountsCount: accounts.filter((item) => item.is_active).length,
      categoriesCount: categories.length,
      latestTransactions,
    };
  }, [accountsQuery.data, categoriesQuery.data, transactionsQuery.data]);

  const isLoading = accountsQuery.isLoading || categoriesQuery.isLoading || transactionsQuery.isLoading;
  const isError = accountsQuery.isError || categoriesQuery.isError || transactionsQuery.isError;

  return (
    <PageShell title="Обзор" description="Стартовый экран личного кабинета: ключевые показатели, контроль проверки и последние операции.">
      {isLoading ? <LoadingState title="Собираем дашборд..." description="Загружаем счета, категории и транзакции." /> : null}

      {isError ? <ErrorState title="Не удалось загрузить дашборд" description="Проверь доступность backend API и повтори попытку." /> : null}

      {!isLoading && !isError ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Общий баланс" value={<MoneyAmount value={stats.totalBalance} className="text-2xl lg:text-3xl" />} hint="Сумма по всем счетам" icon={<Wallet className="size-5" />} />
            <StatCard label="Доходы в аналитике" value={<MoneyAmount value={stats.income} tone="income" className="text-2xl lg:text-3xl" />} hint="Все доходные операции" icon={<ArrowUpCircle className="size-5" />} />
            <StatCard label="Расходы в аналитике" value={<MoneyAmount value={stats.expense} tone="expense" className="text-2xl lg:text-3xl" />} hint="Все расходные операции" icon={<ArrowDownCircle className="size-5" />} />
            <StatCard label="Требуют проверки" value={stats.reviewCount} hint="Операции для ручной валидации" icon={<ListChecks className="size-5" />} />
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.35fr_0.85fr]">
            <Card className="p-5 lg:p-6">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-slate-950">Последние транзакции</h3>
                  <p className="mt-1 text-sm text-slate-500">Быстрый обзор последних операций в системе.</p>
                </div>
              </div>

              <div className="mt-5 space-y-3">
                {stats.latestTransactions.length === 0 ? (
                  <div className="surface-muted p-5 text-sm text-slate-500">Пока нет транзакций. Добавь первую операцию, чтобы увидеть активность.</div>
                ) : (
                  stats.latestTransactions.map((item) => (
                    <div key={item.id} className="surface-muted flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-900">{item.description || 'Операция без описания'}</p>
                        <p className="mt-1 text-sm text-slate-500">{formatDateTime(item.transaction_date)}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        {item.needs_review ? <StatusBadge tone="warning">Проверить</StatusBadge> : null}
                        <MoneyAmount value={item.type === 'expense' ? -Number(item.amount) : Number(item.amount)} currency={item.currency} tone={item.type === 'expense' ? 'expense' : 'income'} showSign />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </Card>

            <div className="grid gap-4">
              <StatCard label="Счета" value={stats.accountsCount} hint={`Активных: ${stats.activeAccountsCount}`} icon={<CreditCard className="size-5" />} />
              <StatCard label="Категории" value={stats.categoriesCount} hint="Справочник доходов и расходов" icon={<FolderTree className="size-5" />} />
              <Card className="p-5 lg:p-6">
                <h3 className="text-lg font-semibold text-slate-950">Что уже готово</h3>
                <div className="mt-4 flex flex-wrap gap-2">
                  <StatusBadge tone="success">Счета</StatusBadge>
                  <StatusBadge tone="success">Категории</StatusBadge>
                  <StatusBadge tone="success">Транзакции</StatusBadge>
                  <StatusBadge tone="info">Дашборд</StatusBadge>
                </div>
                <p className="mt-4 text-sm leading-6 text-slate-500">UI приведён к единому стилю: единые карточки, статусы, отображение сумм и поведение базовых экранов.</p>
              </Card>
            </div>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
