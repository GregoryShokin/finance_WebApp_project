"use client";

import { CreditCard, Pencil, Trash2, Wallet } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { MoneyAmount } from '@/components/shared/money-amount';
import { StatusBadge } from '@/components/shared/status-badge';
import type { Account } from '@/types/account';

export function AccountCard({
  account,
  onEdit,
  onDelete,
  isDeleting,
}: {
  account: Account;
  onEdit: (account: Account) => void;
  onDelete: (account: Account) => void;
  isDeleting?: boolean;
}) {
  const numericBalance = Number(account.balance);

  return (
    <Card className="p-5 lg:p-6">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
              {account.is_credit ? <CreditCard className="size-5" /> : <Wallet className="size-5" />}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-lg font-semibold text-slate-950">{account.name}</h3>
                <StatusBadge tone={account.is_active ? 'success' : 'neutral'}>
                  {account.is_active ? 'Активный' : 'Неактивный'}
                </StatusBadge>
                {account.is_credit ? <StatusBadge tone="warning">Кредитный</StatusBadge> : null}
              </div>
              <p className="mt-1 text-sm text-slate-500">Валюта счёта: {account.currency}</p>
            </div>
          </div>

          <div className="surface-muted mt-5 p-4">
            <p className="text-sm text-slate-500">Текущий баланс</p>
            <MoneyAmount
              value={numericBalance}
              currency={account.currency}
              tone={numericBalance < 0 ? 'expense' : 'default'}
              className="mt-1 block text-2xl lg:text-3xl"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          <Button
            type="button"
            variant="secondary"
            size="icon"
            onClick={() => onEdit(account)}
            aria-label="Изменить счёт"
            title="Изменить"
          >
            <Pencil className="size-4" />
          </Button>
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
        </div>
      </div>
    </Card>
  );
}
