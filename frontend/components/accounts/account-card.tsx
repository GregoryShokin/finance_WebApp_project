"use client";

import { CreditCard, Pencil, RotateCcw, Trash2, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import type { Account } from '@/types/account';

function CreditCardLimitBar({ account }: { account: Account }) {
  const limit = Number(account.credit_limit_original ?? 0);
  if (limit <= 0) return null;

  const balance = Number(account.balance);
  const used = Math.max(0, limit - balance);
  const pct = Math.min(100, (used / limit) * 100);

  const barColor =
    pct > 80 ? 'bg-rose-500' : pct > 50 ? 'bg-amber-400' : 'bg-emerald-500';

  const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

  return (
    <div className="mt-4">
      <div className="mb-1 flex justify-between text-xs text-slate-500">
        <span>Использовано лимита</span>
        <span>{fmt(used)} из {fmt(limit)} ₽</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function AccountCard({
  account,
  onEdit,
  onDelete,
  onCancelDelete,
  isDeletePending,
  isDeleting,
}: {
  account: Account;
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  onCancelDelete: (accountId: number) => void;
  isDeletePending?: boolean;
  isDeleting?: boolean;
}) {
  const numericBalance = Number(account.balance);
  const isCreditCard = account.account_type === 'credit_card';

  return (
    <Card className="p-5 lg:p-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
              {account.is_credit || isCreditCard ? <CreditCard className="size-5" /> : <Wallet className="size-5" />}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-lg font-semibold text-slate-950">{account.name}</h3>
                <StatusBadge tone={account.is_active ? 'success' : 'neutral'}>
                  {account.is_active ? 'Активный' : 'Неактивный'}
                </StatusBadge>
                {isCreditCard ? <StatusBadge tone="warning">Кредитная карта</StatusBadge> : null}
                {account.is_credit && !isCreditCard ? <StatusBadge tone="warning">Кредит</StatusBadge> : null}
              </div>
              <p className="mt-1 text-sm text-slate-500">Валюта счёта: {account.currency}</p>
            </div>
          </div>

          <div className="surface-muted mt-5 p-4">
            <p className="text-sm text-slate-500">
              {isCreditCard ? 'Доступный остаток' : account.is_credit ? 'Текущий долг' : 'Текущий баланс'}
            </p>
            <MoneyAmount
              value={numericBalance}
              currency={account.currency}
              tone={numericBalance < 0 ? 'expense' : 'default'}
              className="mt-1 block text-2xl lg:text-3xl"
            />
            {isCreditCard ? <CreditCardLimitBar account={account} /> : null}
          </div>

          {account.is_credit && !isCreditCard ? (
            <div className="mt-4 grid gap-3 text-sm text-slate-600 sm:grid-cols-3">
              <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                <div className="text-xs text-slate-500">Изначальная сумма</div>
                <div className="mt-1 font-medium text-slate-900">{Number(account.credit_limit_original ?? 0).toLocaleString('ru-RU')}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                <div className="text-xs text-slate-500">Ставка</div>
                <div className="mt-1 font-medium text-slate-900">{Number(account.credit_interest_rate ?? 0).toLocaleString('ru-RU')}%</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-white px-3 py-2">
                <div className="text-xs text-slate-500">Осталось</div>
                <div className="mt-1 font-medium text-slate-900">{Number(account.credit_term_remaining ?? 0).toLocaleString('ru-RU')} мес.</div>
              </div>
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <Button type="button" variant="secondary" size="icon" onClick={() => onEdit(account)} aria-label="Изменить счёт" title="Изменить">
            <Pencil className="size-4" />
          </Button>
          {isDeletePending ? (
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => onCancelDelete(account.id)}
              disabled={isDeleting}
              aria-label={isDeleting ? 'Счёт удаляется' : 'Отменить удаление счёта'}
              title={isDeleting ? 'Удаляем...' : 'Отменить удаление'}
            >
              <RotateCcw className="size-4" />
            </Button>
          ) : (
            <Button
              type="button"
              variant="danger"
              size="icon"
              onClick={() => onDelete(account)}
              disabled={isDeleting}
              aria-label={isDeleting ? 'Удаляем счёт' : 'Удалить счёт'}
              title={isDeleting ? 'Удаляем...' : 'Удалить'}
            >
              <Trash2 className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
