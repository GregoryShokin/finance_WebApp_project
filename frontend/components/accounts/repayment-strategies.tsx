'use client';

import { useMemo, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { simulateRepayment, type CreditRepaymentInput } from '@/lib/utils/repayment';
import type { Account } from '@/types/account';

interface Props {
  accounts: Account[];
  totalBudget: number;
}

type StrategyTone = 'good' | 'info' | 'neutral';

type StrategyCardProps = {
  title: string;
  description: string;
  badge: string;
  badgeTone: StrategyTone;
  months: number;
  totalInterest: number;
  order: CreditRepaymentInput[];
  detailType: 'rate' | 'balance';
  savedMonths?: number;
  savedMoney?: number;
};

function pluralize(value: number, one: string, few: string, many: string) {
  const mod10 = value % 10;
  const mod100 = value % 100;

  if (mod100 >= 11 && mod100 <= 19) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function toNumber(value: string | number | null | undefined) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function getMonthlyPayment(account: Account) {
  const explicitPayment = Math.max(0, toNumber(account.monthly_payment));
  if (explicitPayment > 0) return explicitPayment;

  const balance = Math.max(0, toNumber(account.balance));
  const rate = Math.max(0, toNumber(account.credit_interest_rate));
  const remainingMonths = Math.max(0, Number(account.credit_term_remaining ?? 0));

  if (balance <= 0 || remainingMonths <= 0) return 0;

  const monthlyRate = rate / 100 / 12;
  if (monthlyRate <= 0) return balance / remainingMonths;

  const factor = Math.pow(1 + monthlyRate, remainingMonths);
  return factor > 1 ? (balance * monthlyRate * factor) / (factor - 1) : 0;
}

function formatDuration(months: number) {
  const years = Math.floor(months / 12);
  const restMonths = months % 12;
  const parts: string[] = [];

  if (years > 0) {
    parts.push(`${years} ${pluralize(years, 'год', 'года', 'лет')}`);
  }

  if (restMonths > 0 || parts.length === 0) {
    parts.push(`${restMonths} ${pluralize(restMonths, 'месяц', 'месяца', 'месяцев')}`);
  }

  return parts.join(' ');
}

function formatRate(rate: number) {
  return rate.toLocaleString('ru-RU', { maximumFractionDigits: 2 });
}

function badgeClass(tone: StrategyTone) {
  if (tone === 'good') return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
  if (tone === 'info') return 'bg-sky-50 text-sky-700 ring-sky-200';
  return 'bg-slate-100 text-slate-600 ring-slate-200';
}

function StrategyCard({
  title,
  description,
  badge,
  badgeTone,
  months,
  totalInterest,
  order,
  detailType,
  savedMonths = 0,
  savedMoney = 0,
}: StrategyCardProps) {
  const hasSavedMonths = savedMonths > 0;
  const hasSavedMoney = savedMoney > 0;
  const hasSavings = hasSavedMonths || hasSavedMoney;
  const extraPaymentSummary = hasSavedMonths && hasSavedMoney
    ? `С доп. взносом: закроешь на ${savedMonths} мес раньше, сэкономишь ${formatMoney(savedMoney)}`
    : hasSavedMonths
      ? `С доп. взносом: закроешь на ${savedMonths} мес раньше`
      : `С доп. взносом: сэкономишь ${formatMoney(savedMoney)}`;

  return (
    <div className="rounded-3xl border border-white/60 bg-white/85 p-5 shadow-soft">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="text-base font-semibold text-slate-950">{title}</h3>
          <p className="text-sm text-slate-500">{description}</p>
        </div>
        <span
          className={cn(
            'inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset',
            badgeClass(badgeTone),
          )}
        >
          {badge}
        </span>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl bg-slate-50/80 p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Срок погашения</p>
          <p className="mt-2 text-lg font-semibold text-slate-950">{formatDuration(months)}</p>
          {hasSavedMonths ? (
            <p className="mt-2 text-sm font-medium text-emerald-700">{`Экономия времени: −${savedMonths} мес`}</p>
          ) : null}
        </div>
        <div className="rounded-2xl bg-slate-50/80 p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Переплата процентов</p>
          <p className="mt-2 text-lg font-semibold text-slate-950">{formatMoney(totalInterest)}</p>
          {hasSavedMoney ? (
            <p className="mt-2 text-sm font-medium text-emerald-700">{`Экономия процентов: −${formatMoney(savedMoney)}`}</p>
          ) : null}
        </div>
      </div>

      {hasSavings ? (
        <div className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-700">
          {extraPaymentSummary}
        </div>
      ) : null}

      <div className="mt-5">
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Очерёдность</p>
        <ol className="mt-3 space-y-2">
          {order.map((credit, index) => (
            <li key={credit.id} className="flex gap-3 rounded-2xl bg-slate-50/70 px-4 py-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-white text-xs font-semibold text-slate-500 ring-1 ring-inset ring-slate-200">
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900">{credit.name}</p>
                <p className="text-xs text-slate-500">
                  {detailType === 'rate'
                    ? `Ставка ${formatRate(credit.rate)}%`
                    : `Остаток ${formatMoney(credit.balance)}`}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

export function RepaymentStrategies({ accounts, totalBudget }: Props) {
  const [collapsed, setCollapsed] = useState(true);
  const [extraPayment, setExtraPayment] = useState(0);

  const avalancheSortFn = (a: CreditRepaymentInput, b: CreditRepaymentInput) =>
    b.rate - a.rate || a.balance - b.balance || a.id - b.id;
  const snowballSortFn = (a: CreditRepaymentInput, b: CreditRepaymentInput) =>
    a.balance - b.balance || b.rate - a.rate || a.id - b.id;

  const credits = useMemo<CreditRepaymentInput[]>(() => {
    return accounts
      .filter((account) => account.account_type === 'loan' && Math.abs(toNumber(account.balance)) > 0)
      .map((account) => ({
        id: account.id,
        name: account.name,
        balance: Math.abs(toNumber(account.balance)),
        rate: Math.max(0, toNumber(account.credit_interest_rate)),
        minPayment: Math.max(0, getMonthlyPayment(account)),
      }));
  }, [accounts]);

  const visible = credits.length >= 2;
  const budget = Math.max(0, Number(totalBudget) || 0);
  const effectiveBudget = budget + extraPayment;
  const extraBudget = Math.max(0, effectiveBudget - budget);
  const allRatesEqual =
    credits.length > 0 &&
    credits.every((credit) => Math.abs(credit.rate - credits[0].rate) < 0.0001);
  const equalRateLabel = credits[0] ? formatRate(credits[0].rate) : '0';

  const baseAvalanche = useMemo(
    () => (extraPayment > 0 ? simulateRepayment(credits, 0, avalancheSortFn) : null),
    [credits, extraPayment],
  );
  const baseSnowball = useMemo(
    () => (extraPayment > 0 ? simulateRepayment(credits, 0, snowballSortFn) : null),
    [credits, extraPayment],
  );
  const avalanche = useMemo(
    () => simulateRepayment(credits, extraBudget, avalancheSortFn),
    [credits, extraBudget, effectiveBudget],
  );
  const snowball = useMemo(
    () => simulateRepayment(credits, extraBudget, snowballSortFn),
    [credits, extraBudget, effectiveBudget],
  );

  const avalancheOrder = useMemo(() => {
    const rank = new Map(avalanche.order.map((name, index) => [name, index]));
    return [...credits].sort(
      (a, b) =>
        (rank.get(a.name) ?? Number.MAX_SAFE_INTEGER) -
          (rank.get(b.name) ?? Number.MAX_SAFE_INTEGER) ||
        b.rate - a.rate ||
        a.balance - b.balance ||
        a.id - b.id,
    );
  }, [avalanche.order, credits]);

  const snowballOrder = useMemo(() => {
    const rank = new Map(snowball.order.map((name, index) => [name, index]));
    return [...credits].sort(
      (a, b) =>
        (rank.get(a.name) ?? Number.MAX_SAFE_INTEGER) -
          (rank.get(b.name) ?? Number.MAX_SAFE_INTEGER) ||
        a.balance - b.balance ||
        b.rate - a.rate ||
        a.id - b.id,
    );
  }, [snowball.order, credits]);

  const interestSavings = Math.max(0, snowball.totalInterest - avalanche.totalInterest);
  const monthSavings = Math.max(0, snowball.months - avalanche.months);
  const avalancheTimeSaved =
    extraPayment > 0 && baseAvalanche ? Math.max(0, baseAvalanche.months - avalanche.months) : 0;
  const avalancheInterestSaved =
    extraPayment > 0 && baseAvalanche ? Math.max(0, baseAvalanche.totalInterest - avalanche.totalInterest) : 0;
  const snowballTimeSaved =
    extraPayment > 0 && baseSnowball ? Math.max(0, baseSnowball.months - snowball.months) : 0;
  const snowballInterestSaved =
    extraPayment > 0 && baseSnowball ? Math.max(0, baseSnowball.totalInterest - snowball.totalInterest) : 0;
  const bestSavedMonths = Math.max(avalancheTimeSaved, snowballTimeSaved);
  const summaryText =
    extraPayment === 0
      ? 'Введи доп. взнос — посмотри сколько сэкономишь'
      : allRatesEqual
        ? `+${formatMoney(extraPayment)}/мес закроют долги на ${bestSavedMonths} мес раньше`
        : interestSavings > 0
          ? `+${formatMoney(extraPayment)}/мес сэкономят ${formatMoney(avalancheInterestSaved)} и закроют долги на ${avalancheTimeSaved} мес раньше`
          : `+${formatMoney(extraPayment)}/мес закроют долги на ${bestSavedMonths} мес раньше`;

  if (!visible) {
    return null;
  }

  return (
    <section className="rounded-3xl border border-white/60 bg-white/85 shadow-soft">
      <button
        type="button"
        onClick={() => setCollapsed((prev) => !prev)}
        className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left"
      >
        <div className="min-w-0">
          <p className="text-base font-semibold text-slate-950">Стратегии погашения</p>
          <p className="mt-1 text-sm text-slate-500">
            {summaryText}
          </p>
          {allRatesEqual ? (
            <div className="mt-3 rounded-xl border border-amber-100 bg-amber-50 px-4 py-3 text-xs text-amber-800">
              <p>{`У всех кредитов одинаковая ставка (${equalRateLabel}%) — обе стратегии дают одинаковый финансовый результат.`}</p>
              <p className="mt-1">Снежный ком поможет быстрее закрыть первый кредит и психологически легче.</p>
            </div>
          ) : null}
        </div>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          {collapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
        </span>
      </button>

      {!collapsed ? (
        <div className="border-t border-slate-100 px-5 py-5">
          <div className="rounded-3xl border border-slate-200/80 bg-slate-50/80 p-5">
            <p className="text-sm font-semibold text-slate-900">
              Дополнительный взнос сверх минимальных платежей
            </p>
            <input
              type="range"
              min={0}
              max={100000}
              step={1000}
              value={extraPayment}
              onChange={(event) => setExtraPayment(Number(event.target.value))}
              className="mt-4 h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-200 accent-emerald-500"
            />
            <div className="mt-3 flex flex-col gap-2 text-sm sm:flex-row sm:items-center sm:justify-between">
              <p className="text-slate-500">{`Текущий платёж: ${formatMoney(budget)}/мес`}</p>
              <p
                className={cn(
                  'font-semibold text-slate-900',
                  extraPayment > 0 && 'text-emerald-700',
                )}
              >
                {`Итого: ${formatMoney(effectiveBudget)}/мес`}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <StrategyCard
              title="Лавина"
              description="Сначала закрываем самый дорогой долг по ставке."
              badge={interestSavings > 0 ? 'Выгоднее' : 'Без экономии'}
              badgeTone={interestSavings > 0 ? 'good' : 'neutral'}
              months={avalanche.months}
              totalInterest={avalanche.totalInterest}
              order={avalancheOrder}
              detailType="rate"
              savedMonths={avalancheTimeSaved}
              savedMoney={avalancheInterestSaved}
            />
            <StrategyCard
              title="Снежный ком"
              description="Сначала закрываем самый маленький долг для быстрого прогресса."
              badge="Мотивирует"
              badgeTone="info"
              months={snowball.months}
              totalInterest={snowball.totalInterest}
              order={snowballOrder}
              detailType="balance"
              savedMonths={snowballTimeSaved}
              savedMoney={snowballInterestSaved}
            />
          </div>

          {interestSavings > 0 ? (
            <div className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 ring-1 ring-inset ring-emerald-200">
              {`Лавина сэкономит ${formatMoney(interestSavings)} и закроет долги на ${monthSavings} мес. раньше`}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
