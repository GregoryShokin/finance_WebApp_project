"use client";

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowDownCircle,
  ArrowUpCircle,
  ArrowRight,
  Bell,
  CreditCard,
  FolderTree,
  HandCoins,
  ListChecks,
  Scale,
  TrendingDown,
  TrendingUp,
  Trash2,
  X,
  Wallet,
} from 'lucide-react';
import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, LoadingState } from '@/components/states/page-state';
import { StatCard } from '@/components/shared/stat-card';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getAccounts } from '@/lib/api/accounts';
import { getCategories } from '@/lib/api/categories';
import { getTransactions } from '@/lib/api/transactions';
import { getCounterparties, deleteCounterparty } from '@/lib/api/counterparties';
import { getFinancialHealth } from '@/lib/api/financial-health';
import { getBudgetAlerts, getBudgetProgress, markAlertRead } from '@/lib/api/budget';
import { getMetrics } from '@/lib/api/metrics';
import { FinancialIndependenceWidget } from '@/components/planning/financial-independence-widget';
import { SavingsRateWidget } from '@/components/planning/savings-rate-widget';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import { formatDateTime, formatMoney } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { toast } from 'sonner';
import type { HealthStatus } from '@/types/financial-health';
import type { BudgetAlert, BudgetAlertType } from '@/types/budget';

// ── Date constants (module-level) ────────────────────────────────────────────

const _today = new Date();
const _thisMonthStart = new Date(_today.getFullYear(), _today.getMonth(), 1);
const _prevMonthStart = new Date(_today.getFullYear(), _today.getMonth() - 1, 1);
const _prevMonthEnd = new Date(_today.getFullYear(), _today.getMonth(), 0);

function _toISO(d: Date) {
  return d.toISOString().split('T')[0];
}

const THIS_MONTH_FROM = _toISO(_thisMonthStart);
const THIS_MONTH_KEY = `${_today.getFullYear()}-${String(_today.getMonth() + 1).padStart(2, '0')}`;
const THIS_MONTH_TO = _toISO(_today);
const PREV_MONTH_FROM = _toISO(_prevMonthStart);
const PREV_MONTH_TO = _toISO(_prevMonthEnd);
const DAYS_IN_MONTH = new Date(_today.getFullYear(), _today.getMonth() + 1, 0).getDate();
const DAYS_PASSED = _today.getDate();
const MONTH_NAME = _today.toLocaleString('ru-RU', { month: 'long' });

// ── Helpers ───────────────────────────────────────────────────────────────────

function statusColors(status: HealthStatus) {
  if (status === 'danger') return { dot: 'bg-rose-500', text: 'text-rose-600', badge: 'bg-rose-100 text-rose-700' };
  if (status === 'warning') return { dot: 'bg-amber-400', text: 'text-amber-600', badge: 'bg-amber-100 text-amber-700' };
  return { dot: 'bg-emerald-500', text: 'text-emerald-600', badge: 'bg-emerald-100 text-emerald-700' };
}

function statusLabel(status: HealthStatus) {
  if (status === 'danger') return 'Высокая';
  if (status === 'warning') return 'Умеренная';
  return 'Нормальная';
}

function budgetBarColor(pct: number) {
  if (pct >= 90) return 'bg-rose-500';
  if (pct >= 70) return 'bg-amber-400';
  return 'bg-emerald-500';
}

function alertStyle(type: BudgetAlertType) {
  // anomaly and budget exceeded → danger (red); 80% warning and forecast → warning (amber)
  const isDanger = type === 'anomaly';
  return isDanger
    ? { card: 'border-rose-200 bg-rose-50', icon: 'text-rose-500', text: 'text-rose-900', sub: 'text-rose-600', btn: 'text-rose-400 hover:text-rose-600 hover:bg-rose-100' }
    : { card: 'border-amber-200 bg-amber-50', icon: 'text-amber-500', text: 'text-amber-900', sub: 'text-amber-600', btn: 'text-amber-400 hover:text-amber-600 hover:bg-amber-100' };
}

function alertTitle(type: BudgetAlertType) {
  if (type === 'budget_80_percent') return 'Бюджет почти исчерпан';
  if (type === 'anomaly') return 'Аномальные расходы';
  return 'Прогноз дефицита';
}

function DeltaBadge({ delta, inverse = false }: { delta: number | null; inverse?: boolean }) {
  if (delta === null || !Number.isFinite(delta)) return null;
  const isPositive = delta >= 0;
  const isGood = inverse ? !isPositive : isPositive;
  return (
    <span className={cn('ml-1.5 text-xs font-medium tabular-nums', isGood ? 'text-emerald-600' : 'text-rose-600')}>
      {isPositive ? '+' : ''}{delta.toFixed(1)}%
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const queryClient = useQueryClient();

  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'dashboard'], queryFn: () => getCategories() });
  const transactionsQuery = useQuery({ queryKey: ['transactions', 'dashboard'], queryFn: () => getTransactions() });
  const counterpartiesQuery = useQuery({ queryKey: ['counterparties'], queryFn: getCounterparties });
  const healthQuery = useQuery({ queryKey: ['financial-health'], queryFn: getFinancialHealth });
  const budgetQuery = useQuery({
    queryKey: ['budget', THIS_MONTH_FROM],
    queryFn: () => getBudgetProgress(THIS_MONTH_FROM),
  });

  const alertsQuery = useQuery({
    queryKey: ['budget-alerts'],
    queryFn: getBudgetAlerts,
  });

  const metricsQuery = useQuery({
    queryKey: ['metrics', THIS_MONTH_KEY],
    queryFn: () => getMetrics(THIS_MONTH_KEY),
  });

  const dismissAlertMutation = useMutation({
    mutationFn: (alertId: number) => markAlertRead(alertId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['budget-alerts'] }),
  });

  const thisMonthQuery = useQuery({
    queryKey: ['transactions', 'this-month', THIS_MONTH_FROM, THIS_MONTH_TO],
    queryFn: () => getTransactions({ date_from: THIS_MONTH_FROM, date_to: THIS_MONTH_TO }),
  });

  const prevMonthQuery = useQuery({
    queryKey: ['transactions', 'prev-month', PREV_MONTH_FROM, PREV_MONTH_TO],
    queryFn: () => getTransactions({ date_from: PREV_MONTH_FROM, date_to: PREV_MONTH_TO }),
  });

  const deleteCounterpartyMutation = useMutation({
    mutationFn: deleteCounterparty,
    onSuccess: async () => {
      toast.success('Контрагент удалён');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['counterparties'] }),
        queryClient.invalidateQueries({ queryKey: ['transactions'] }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось удалить контрагента'),
  });

  // ── KPI metrics ────────────────────────────────────────────────────────────

  const [debtMode, setDebtMode] = useState<'basic' | 'extended'>('basic');

  const kpi = useMemo(() => {
    const thisTx = thisMonthQuery.data ?? [];
    const prevTx = prevMonthQuery.data ?? [];

    const thisIncome = thisTx.filter(t => t.type === 'income' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);
    const thisExpense = thisTx.filter(t => t.type === 'expense' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);
    const prevIncome = prevTx.filter(t => t.type === 'income' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);
    const prevExpense = prevTx.filter(t => t.type === 'expense' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);

    const projectedExpense = DAYS_PASSED > 0 ? (thisExpense / DAYS_PASSED) * DAYS_IN_MONTH : 0;
    const projectedBalance = thisIncome - projectedExpense;

    const incomeDelta = prevIncome > 0 ? ((thisIncome - prevIncome) / prevIncome) * 100 : null;
    const expenseDelta = prevExpense > 0 ? ((thisExpense - prevExpense) / prevExpense) * 100 : null;

    const health = healthQuery.data;
    const debtBasic = health?.debt_ratio_basic ?? null;
    const debtExtended = health?.debt_ratio_extended ?? null;

    return {
      thisIncome, thisExpense, incomeDelta, expenseDelta,
      projectedBalance, projectedExpense,
      debtBasic, debtExtended,
      hasExtended: !!debtExtended,
      dti: health?.dti_value ?? null,
      dtiStatus: (health?.dti_status ?? 'normal') as HealthStatus,
    };
  }, [thisMonthQuery.data, prevMonthQuery.data, healthQuery.data]);

  // ── General stats ──────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const accounts = accountsQuery.data ?? [];
    const categories = categoriesQuery.data ?? [];
    const transactions = transactionsQuery.data ?? [];
    const counterparties = counterpartiesQuery.data ?? [];

    const totalBalance = accounts.reduce((sum, a) => sum + Number(a.balance), 0);
    const income = transactions.filter(t => t.type === 'income' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);
    const expense = transactions.filter(t => t.type === 'expense' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);
    const reviewCount = transactions.filter(t => t.needs_review).length;
    const latestTransactions = [...transactions]
      .sort((a, b) => new Date(b.transaction_date).getTime() - new Date(a.transaction_date).getTime())
      .slice(0, 5);
    const debtReceivable = counterparties.reduce((s, c) => s + Number(c.receivable_amount), 0);
    const debtPayable = counterparties.reduce((s, c) => s + Number(c.payable_amount), 0);
    const activeCounterparties = counterparties.filter(c => Number(c.receivable_amount) > 0 || Number(c.payable_amount) > 0);

    return {
      totalBalance, income, expense, reviewCount,
      accounts,
      accountsCount: accounts.length,
      activeAccountsCount: accounts.filter(a => a.is_active).length,
      categoriesCount: categories.length,
      latestTransactions, debtReceivable, debtPayable, activeCounterparties,
    };
  }, [accountsQuery.data, categoriesQuery.data, transactionsQuery.data, counterpartiesQuery.data]);

  const isLoading = accountsQuery.isLoading || categoriesQuery.isLoading || transactionsQuery.isLoading || counterpartiesQuery.isLoading;
  const isError = accountsQuery.isError || categoriesQuery.isError || transactionsQuery.isError || counterpartiesQuery.isError;
  const kpiLoading = thisMonthQuery.isLoading || prevMonthQuery.isLoading || healthQuery.isLoading;

  // Top-5 budget categories sorted by percent_used desc
  const topBudget = useMemo(
    () => [...(budgetQuery.data ?? [])].sort((a, b) => b.percent_used - a.percent_used).slice(0, 5),
    [budgetQuery.data],
  );

  return (
    <PageShell title="Обзор" description="Ключевые финансовые показатели, проверка операций, долги и последние транзакции.">
      {isLoading ? <LoadingState title="Собираем дашборд..." description="Загружаем счета, категории, транзакции и контрагентов." /> : null}
      {isError ? <ErrorState title="Не удалось загрузить дашборд" description="Проверь доступность backend API и повтори попытку." /> : null}

      {!isLoading && !isError ? (
        <>
          {/* ── Metrics row ────────────────────────────────────────────────── */}
          <div className="flex gap-4">
            <div style={{ flex: '1 1 0' }}>
              <FinancialIndependenceWidget
                data={metricsQuery.data?.financial_independence}
                isLoading={metricsQuery.isLoading}
              />
            </div>
            <Card className="p-5" style={{ flex: '1 1 0' }}>
              <p className="text-xs font-medium text-slate-500">Норма сбережений</p>
              <div className="mt-2">
                <SavingsRateWidget
                  data={metricsQuery.data?.savings_rate}
                  isLoading={metricsQuery.isLoading}
                />
              </div>
            </Card>
          </div>

          {/* ── KPI row ────────────────────────────────────────────────────── */}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">

            {/* 1. Свободные средства */}
            <Card className="p-5 lg:p-6">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-slate-500">Свободные средства</p>
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
                  {kpi.projectedBalance >= 0 ? <TrendingUp className="size-5" /> : <TrendingDown className="size-5" />}
                </div>
              </div>
              {kpiLoading ? (
                <div className="mt-3 h-8 w-32 animate-pulse rounded bg-slate-100" />
              ) : (
                <div className={cn('mt-3 text-2xl font-semibold lg:text-3xl', kpi.projectedBalance >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
                  {formatMoney(kpi.projectedBalance)}
                </div>
              )}
              <p className="mt-2 text-sm text-slate-500">прогноз на конец {MONTH_NAME}</p>
              {!kpiLoading && (
                <p className="mt-1 text-xs text-slate-400">
                  расходы ≈ {formatMoney(kpi.projectedExpense)} · {DAYS_PASSED} из {DAYS_IN_MONTH} дн.
                </p>
              )}
            </Card>

            {/* 2. Доходы / Расходы */}
            <Card className="p-5 lg:p-6">
              <p className="text-sm font-medium text-slate-500">Доходы и расходы</p>
              <p className="mt-0.5 text-xs text-slate-400 capitalize">{MONTH_NAME}</p>
              {kpiLoading ? (
                <div className="mt-3 space-y-2">
                  <div className="h-6 w-28 animate-pulse rounded bg-slate-100" />
                  <div className="h-6 w-28 animate-pulse rounded bg-slate-100" />
                </div>
              ) : (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center">
                    <ArrowUpCircle className="mr-2 size-4 shrink-0 text-emerald-500" />
                    <span className="text-lg font-semibold text-emerald-600 tabular-nums">{formatMoney(kpi.thisIncome)}</span>
                    <DeltaBadge delta={kpi.incomeDelta} inverse={false} />
                  </div>
                  <div className="flex items-center">
                    <ArrowDownCircle className="mr-2 size-4 shrink-0 text-rose-500" />
                    <span className="text-lg font-semibold text-rose-600 tabular-nums">{formatMoney(kpi.thisExpense)}</span>
                    <DeltaBadge delta={kpi.expenseDelta} inverse={true} />
                  </div>
                </div>
              )}
              <p className="mt-2 text-xs text-slate-400">% — изменение к прошлому месяцу</p>
            </Card>

            {/* 3. Закредитованность (debt ratio) */}
            <Card className="p-5 lg:p-6">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-slate-500">Закредитованность</p>
                {/* Basic / Extended toggle */}
                <div className="flex shrink-0 overflow-hidden rounded-lg border border-slate-200 text-xs font-medium">
                  <button
                    onClick={() => setDebtMode('basic')}
                    className={cn(
                      'px-2.5 py-1 transition',
                      debtMode === 'basic' ? 'bg-slate-900 text-white' : 'bg-white text-slate-500 hover:bg-slate-50',
                    )}
                  >
                    Базовый
                  </button>
                  <button
                    onClick={() => setDebtMode('extended')}
                    className={cn(
                      'border-l border-slate-200 px-2.5 py-1 transition',
                      debtMode === 'extended' ? 'bg-slate-900 text-white' : 'bg-white text-slate-500 hover:bg-slate-50',
                    )}
                  >
                    С активами
                  </button>
                </div>
              </div>

              {kpiLoading ? (
                <div className="mt-3 h-8 w-32 animate-pulse rounded bg-slate-100" />
              ) : (() => {
                const info = debtMode === 'extended' ? (kpi.debtExtended ?? kpi.debtBasic) : kpi.debtBasic;
                if (!info) return <p className="mt-3 text-sm text-slate-400">Нет данных</p>;

                const netWorth = Number(info.total_assets) - Number(info.total_debt);
                const showExtendedHint = debtMode === 'extended' && !kpi.hasExtended;

                return (
                  <>
                    <div className={cn('mt-3 text-2xl font-semibold lg:text-3xl', netWorth >= 0 ? 'text-slate-950' : 'text-rose-600')}>
                      {formatMoney(netWorth)}
                    </div>
                    <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                      <div
                        className={cn('h-full rounded-full transition-all', statusColors(info.status as HealthStatus).dot)}
                        style={{ width: `${Math.min(100, info.value)}%` }}
                      />
                    </div>
                    <p className="mt-2 text-xs text-slate-400">
                      долги {formatMoney(Number(info.total_debt))} · активы {formatMoney(Number(info.total_assets))}
                    </p>
                    {debtMode === 'extended' && kpi.hasExtended && (
                      <p className="mt-1 text-xs text-slate-400">включая реальные активы</p>
                    )}
                    {showExtendedHint && (
                      <Link href="/planning" className="mt-2 flex items-center gap-1 text-xs font-medium text-sky-600 hover:text-sky-700">
                        Добавить активы для точного расчёта <ArrowRight className="size-3" />
                      </Link>
                    )}
                  </>
                );
              })()}
            </Card>

            {/* 4. DTI */}
            <Card className="p-5 lg:p-6">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium text-slate-500">Кредитная нагрузка</p>
                {!kpiLoading && kpi.dti !== null && (
                  <span className={cn('flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium', statusColors(kpi.dtiStatus).badge)}>
                    <span className={cn('size-1.5 rounded-full', statusColors(kpi.dtiStatus).dot)} />
                    {statusLabel(kpi.dtiStatus)}
                  </span>
                )}
              </div>
              {kpiLoading ? (
                <div className="mt-3 h-8 w-24 animate-pulse rounded bg-slate-100" />
              ) : kpi.dti !== null ? (
                <>
                  <div className={cn('mt-3 text-2xl font-semibold lg:text-3xl', statusColors(kpi.dtiStatus).text)}>
                    {kpi.dti.toFixed(1)}%
                  </div>
                  <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                    <div className={cn('h-full rounded-full transition-all', statusColors(kpi.dtiStatus).dot)} style={{ width: `${Math.min(100, kpi.dti)}%` }} />
                  </div>
                  <p className="mt-2 text-xs text-slate-400">норма &lt;20% · допустимо &lt;40%</p>
                </>
              ) : (
                <p className="mt-3 text-sm text-slate-400">Нет кредитных операций</p>
              )}
            </Card>
          </div>

          {/* ── Accounts + Budget row ────────────────────────────────────── */}
          <div className="grid gap-4 xl:grid-cols-2">

            {/* Балансы по счетам */}
            <Card className="p-5 lg:p-6">
              <h3 className="text-lg font-semibold text-slate-950">Счета</h3>
              <p className="mt-1 text-sm text-slate-500">Текущие балансы и использование кредитных лимитов.</p>
              <div className="mt-5 space-y-3">
                {stats.accounts.length === 0 ? (
                  <div className="surface-muted p-5 text-sm text-slate-500">Нет счетов. Добавь первый счёт в разделе «Счета».</div>
                ) : (
                  stats.accounts.filter(a => a.is_active).map((account) => {
                    const isCreditCard = account.account_type === 'credit_card';
                    const limit = Number(account.credit_limit_original ?? 0);
                    const balance = Number(account.balance);
                    const used = isCreditCard && limit > 0 ? Math.max(0, limit - balance) : 0;
                    const usedPct = isCreditCard && limit > 0 ? Math.min(100, (used / limit) * 100) : 0;
                    const limitBarColor = usedPct >= 80 ? 'bg-rose-500' : usedPct >= 50 ? 'bg-amber-400' : 'bg-emerald-500';

                    return (
                      <div key={account.id} className="surface-muted p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-2.5">
                            <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-slate-200 text-slate-600">
                              {isCreditCard ? <CreditCard className="size-4" /> : <Wallet className="size-4" />}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-slate-900">{account.name}</p>
                              {isCreditCard && (
                                <span className="mt-0.5 inline-flex items-center rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-700">
                                  Кредитная карта
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="shrink-0 text-right">
                            <MoneyAmount value={balance} currency={account.currency} tone={balance < 0 ? 'expense' : 'default'} className="text-sm" />
                          </div>
                        </div>
                        {isCreditCard && limit > 0 && (
                          <div className="mt-3">
                            <div className="mb-1 flex justify-between text-xs text-slate-400">
                              <span>Использовано лимита</span>
                              <span>{Math.round(used).toLocaleString('ru-RU')} из {Math.round(limit).toLocaleString('ru-RU')} ₽</span>
                            </div>
                            <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                              <div className={cn('h-full rounded-full transition-all', limitBarColor)} style={{ width: `${usedPct}%` }} />
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </Card>

            {/* Прогресс бюджета */}
            <Card className="flex flex-col p-5 lg:p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-slate-950">Бюджет</h3>
                  <p className="mt-1 text-sm text-slate-500 capitalize">Топ-5 категорий по расходам · {MONTH_NAME}</p>
                </div>
                <Link
                  href="/planning"
                  className="flex shrink-0 items-center gap-1 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-200"
                >
                  Все категории <ArrowRight className="size-3" />
                </Link>
              </div>

              <div className="mt-5 flex-1 space-y-4">
                {budgetQuery.isLoading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="space-y-1.5">
                      <div className="h-4 w-3/4 animate-pulse rounded bg-slate-100" />
                      <div className="h-2 w-full animate-pulse rounded-full bg-slate-100" />
                    </div>
                  ))
                ) : topBudget.length === 0 ? (
                  <div className="surface-muted p-5 text-sm text-slate-500">
                    Нет данных о бюджете за {MONTH_NAME}.
                  </div>
                ) : (
                  topBudget.map((item) => {
                    const pct = Math.min(item.percent_used, 100);
                    const textColor = item.percent_used >= 90 ? 'text-rose-600' : item.percent_used >= 70 ? 'text-amber-600' : 'text-slate-600';
                    return (
                      <div key={item.category_id}>
                        <div className="mb-1.5 flex items-center justify-between gap-3">
                          <span className="truncate text-sm font-medium text-slate-900">{item.category_name}</span>
                          <span className={cn('shrink-0 text-xs font-semibold tabular-nums', textColor)}>
                            {item.percent_used.toFixed(0)}%
                          </span>
                        </div>
                        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                          <div
                            className={cn('h-full rounded-full transition-all', budgetBarColor(item.percent_used))}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <div className="mt-1 flex justify-between text-xs text-slate-400">
                          <span>{formatMoney(item.spent_amount)}</span>
                          <span>из {formatMoney(item.planned_amount)}</span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </Card>
          </div>

          {/* ── General stats ─────────────────────────────────────────────── */}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Общий баланс" value={<MoneyAmount value={stats.totalBalance} className="text-2xl lg:text-3xl" />} hint="Сумма по всем счетам" icon={<Wallet className="size-5" />} />
            <StatCard label="Доходы (всего)" value={<MoneyAmount value={stats.income} tone="income" className="text-2xl lg:text-3xl" />} hint="Все доходные операции" icon={<ArrowUpCircle className="size-5" />} />
            <StatCard label="Расходы (всего)" value={<MoneyAmount value={stats.expense} tone="expense" className="text-2xl lg:text-3xl" />} hint="Все расходные операции" icon={<ArrowDownCircle className="size-5" />} />
            <StatCard label="Требуют проверки" value={stats.reviewCount} hint="Операции для ручной валидации" icon={<ListChecks className="size-5" />} />
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Мне должны" value={<MoneyAmount value={stats.debtReceivable} tone="income" className="text-2xl lg:text-3xl" />} hint="Текущая дебиторка по долгам" icon={<HandCoins className="size-5" />} />
            <StatCard label="Я должен" value={<MoneyAmount value={stats.debtPayable} tone="expense" className="text-2xl lg:text-3xl" />} hint="Текущая кредиторка по долгам" icon={<HandCoins className="size-5" />} />
            <StatCard label="Счета" value={stats.accountsCount} hint={`Активных: ${stats.activeAccountsCount}`} icon={<CreditCard className="size-5" />} />
            <StatCard label="Категории" value={stats.categoriesCount} hint="Справочник доходов и расходов" icon={<FolderTree className="size-5" />} />
          </div>

          {/* ── Budget alerts ─────────────────────────────────────────────── */}
          {alertsQuery.data && alertsQuery.data.length > 0 && (
            <div>
              <div className="mb-3 flex items-center gap-2">
                <Bell className="size-4 text-slate-500" />
                <h3 className="text-sm font-semibold text-slate-700">Уведомления по бюджету</h3>
                <span className="flex size-5 items-center justify-center rounded-full bg-rose-500 text-xs font-semibold text-white">
                  {alertsQuery.data.length}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {alertsQuery.data.map((alert: BudgetAlert) => {
                  const s = alertStyle(alert.alert_type);
                  return (
                    <div key={alert.id} className={cn('flex gap-3 rounded-2xl border p-4', s.card)}>
                      <div className="mt-0.5 shrink-0">
                        <AlertTriangle className={cn('size-4', s.icon)} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className={cn('text-sm font-semibold', s.text)}>{alertTitle(alert.alert_type)}</p>
                        <p className={cn('mt-1 text-xs leading-5', s.sub)}>{alert.message}</p>
                      </div>
                      <button
                        onClick={() => dismissAlertMutation.mutate(alert.id)}
                        disabled={dismissAlertMutation.isPending}
                        className={cn('mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg transition', s.btn)}
                        aria-label="Закрыть"
                      >
                        <X className="size-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Counterparties + Latest transactions ──────────────────────── */}
          <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
            <Card className="p-5 lg:p-6">
              <h3 className="text-lg font-semibold text-slate-950">Должники и кредиторы</h3>
              <p className="mt-1 text-sm text-slate-500">Список контрагентов с текущими остатками по долгам.</p>
              <div className="mt-5 space-y-3">
                {stats.activeCounterparties.length === 0 ? (
                  <div className="surface-muted p-5 text-sm text-slate-500">Активных долгов пока нет.</div>
                ) : (
                  stats.activeCounterparties.map((item) => (
                    <div key={item.id} className="surface-muted flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="font-medium text-slate-900">{item.name}</p>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {Number(item.receivable_amount) > 0 ? <StatusBadge tone="income">Мне должны</StatusBadge> : null}
                          {Number(item.payable_amount) > 0 ? <StatusBadge tone="warning">Я должен</StatusBadge> : null}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right text-sm">
                          {Number(item.receivable_amount) > 0 ? <MoneyAmount value={Number(item.receivable_amount)} tone="income" /> : null}
                          {Number(item.payable_amount) > 0 ? <MoneyAmount value={-Number(item.payable_amount)} tone="expense" /> : null}
                        </div>
                        <Button variant="danger" size="icon" onClick={() => deleteCounterpartyMutation.mutate(item.id)} disabled={deleteCounterpartyMutation.isPending}>
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </Card>

            <Card className="p-5 lg:p-6">
              <h3 className="text-lg font-semibold text-slate-950">Последние транзакции</h3>
              <p className="mt-1 text-sm text-slate-500">Быстрый обзор последних операций в системе.</p>
              <div className="mt-5 space-y-3">
                {stats.latestTransactions.length === 0 ? (
                  <div className="surface-muted p-5 text-sm text-slate-500">Пока нет транзакций. Добавь первую операцию, чтобы увидеть активность.</div>
                ) : (
                  stats.latestTransactions.map((item) => (
                    <div key={item.id} className="surface-muted flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-900">{item.description || item.counterparty_name || 'Операция без описания'}</p>
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
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
