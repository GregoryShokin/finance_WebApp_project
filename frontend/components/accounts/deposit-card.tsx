'use client';

import { useMemo } from 'react';
import { Pencil, PiggyBank, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { BankIcon } from '@/components/ui/bank-icon';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { Account } from '@/types/account';

function startOfDay(date: Date) {
  const normalized = new Date(date);
  normalized.setHours(0, 0, 0, 0);
  return normalized;
}

function parseDate(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : startOfDay(parsed);
}

function formatDate(value?: string | null) {
  const parsed = parseDate(value);
  return parsed ? parsed.toLocaleDateString('ru-RU') : '—';
}

function getCapitalizationLabel(
  capitalizationPeriod: Account['deposit_capitalization_period'],
) {
  if (!capitalizationPeriod) return 'Простые проценты';
  if (capitalizationPeriod === 'daily') return 'Ежедневная капитализация';
  if (capitalizationPeriod === 'monthly') return 'Ежемесячная капитализация';
  if (capitalizationPeriod === 'quarterly') return 'Ежеквартальная капитализация';
  return 'Ежегодная капитализация';
}

function calcDepositIncome(
  balance: number,
  annualRate: number,
  openDate: Date,
  closeDate: Date,
  capitalizationPeriod: string | null | undefined,
): number {
  const totalDays = Math.max(1, (closeDate.getTime() - openDate.getTime()) / 86400000);
  const r = annualRate / 100;

  if (!capitalizationPeriod) {
    return balance * r * (totalDays / 365);
  }

  const periodsPerYear =
    capitalizationPeriod === 'daily'
      ? 365
      : capitalizationPeriod === 'monthly'
        ? 12
        : capitalizationPeriod === 'quarterly'
          ? 4
          : 1;

  const n = (totalDays / 365) * periodsPerYear;
  return balance * (Math.pow(1 + r / periodsPerYear, n) - 1);
}

export function DepositCard({
  account,
  onEdit,
  onDelete,
}: {
  account: Account;
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
}) {
  const today = startOfDay(new Date());
  const openDate = parseDate(account.deposit_open_date);
  const closeDate = parseDate(account.deposit_close_date);
  const rate = Number(account.deposit_interest_rate ?? 0);
  const balance = Math.max(0, Number(account.balance ?? 0));
  const isClosed = Boolean(closeDate && closeDate.getTime() < today.getTime());
  const capitalizationLabel = getCapitalizationLabel(account.deposit_capitalization_period);

  const progress = useMemo(() => {
    if (!openDate || !closeDate) return null;

    const totalMs = closeDate.getTime() - openDate.getTime();
    if (totalMs <= 0) return 100;

    const elapsedMs = Math.min(Math.max(today.getTime() - openDate.getTime(), 0), totalMs);
    return Math.max(0, Math.min(100, (elapsedMs / totalMs) * 100));
  }, [closeDate, openDate, today]);

  const expectedIncome = openDate && closeDate
    ? calcDepositIncome(
        balance,
        Math.max(0, rate),
        openDate,
        closeDate,
        account.deposit_capitalization_period,
      )
    : 0;

  return (
    <div className="rounded-3xl border border-white/60 bg-white/85 p-5 shadow-soft">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            {account.bank ? (
              <div className="relative shrink-0">
                <BankIcon
                  code={account.bank.code}
                  bank={account.bank.name}
                  size={48}
                  className="border border-slate-200"
                />
                <span className="absolute -bottom-1 -right-1 grid size-5 place-items-center rounded-full border border-white bg-emerald-600 text-white shadow-sm">
                  <PiggyBank className="size-2.5" />
                </span>
              </div>
            ) : (
              <div className="grid size-12 shrink-0 place-items-center rounded-2xl bg-emerald-50 text-emerald-700">
                <PiggyBank className="size-5" />
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-lg font-semibold text-slate-950">{account.name}</h3>
                <StatusBadge tone={isClosed ? 'neutral' : 'success'}>
                  {isClosed ? 'Закрыт' : 'Активный'}
                </StatusBadge>
              </div>
              {account.bank ? (
                <p className="mt-0.5 text-xs text-slate-500">{account.bank.name}</p>
              ) : null}
            </div>
          </div>

          <MoneyAmount
            value={balance}
            currency={account.currency}
            tone="income"
            className="mt-4 block text-2xl lg:text-3xl"
          />

          <p className="mt-3 text-sm text-slate-500">
            {`Ставка ${Number.isFinite(rate) ? rate.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : '0'}% | ${capitalizationLabel} | Открыт ${formatDate(account.deposit_open_date)} | Закрывается ${formatDate(account.deposit_close_date)}`}
          </p>

          {progress != null ? (
            <div className="mt-4">
              <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
                <span>Срок вклада</span>
                <span>{Math.round(progress)}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className={cn('h-full rounded-full bg-emerald-500 transition-all')}
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          ) : null}

          <div className="mt-4 rounded-2xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
            {`Ожидаемый доход до закрытия: +${formatMoney(expectedIncome)}`}
          </div>
        </div>

        <div className="flex shrink-0 gap-2">
          <Button variant="ghost" size="icon" onClick={() => onEdit(account)} aria-label="Редактировать вклад">
            <Pencil className="size-4" />
          </Button>
          <Button variant="danger" size="icon" onClick={() => onDelete(account)} aria-label="Удалить вклад">
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}