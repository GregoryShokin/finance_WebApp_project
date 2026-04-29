'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown } from 'lucide-react';
import { getAccounts } from '@/lib/api/accounts';
import { cn } from '@/lib/utils/cn';

function formatLastTransactionDate(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date);
}

function diffDaysFromNow(value: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  return Math.max(0, Math.floor(diffMs / (1000 * 60 * 60 * 24)));
}

export function AccountFreshnessBlock() {
  const [isOpen, setIsOpen] = useState(false);
  const accountsQuery = useQuery({ queryKey: ['accounts'], queryFn: getAccounts });

  const accounts = useMemo(
    () =>
      (accountsQuery.data ?? []).filter(
        (account) => account.account_type === 'main' || account.account_type === 'credit_card',
      ),
    [accountsQuery.data],
  );

  if (accountsQuery.isLoading || accounts.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => setIsOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-4 text-left"
        aria-expanded={isOpen}
      >
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Когда последний раз обновлялись счета</h3>
          <p className="mt-1 text-xs text-slate-500">
            Подсказка поможет понять, по какому счёту выписка давно не загружалась.
          </p>
        </div>
        <ChevronDown className={cn('size-4 shrink-0 text-slate-500 transition-transform', isOpen && 'rotate-180')} />
      </button>

      <div
        className={cn(
          'overflow-hidden transition-all duration-300',
          isOpen ? 'max-h-[600px] opacity-100' : 'max-h-0 opacity-0',
        )}
      >
        <div className="flex flex-wrap gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
          {accounts.map((account) => {
            const formattedDate = formatLastTransactionDate(account.last_transaction_date);
            const daysAgo = diffDaysFromNow(account.last_transaction_date);
            const stale = daysAgo !== null && daysAgo > 30;

            return (
              <div
                key={account.id}
                className={cn(
                  'min-w-[210px] flex-1 rounded-2xl border px-3.5 py-3',
                  stale ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white',
                )}
              >
                <p className="text-sm font-medium text-slate-900">{account.name}</p>
                {formattedDate ? (
                  <>
                    <p className={cn('mt-2 text-xs', stale ? 'text-amber-800' : 'text-slate-600')}>
                      {formattedDate}
                    </p>
                    <p className={cn('mt-1 text-xs font-medium', stale ? 'text-amber-700' : 'text-slate-500')}>
                      {daysAgo} дней назад
                    </p>
                  </>
                ) : (
                  <p className="mt-2 text-xs text-slate-500">Транзакций ещё нет</p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
