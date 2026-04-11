'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CreditCard, ShoppingCart, TrendingDown } from 'lucide-react';
import { getLargePurchases } from '@/lib/api/analytics';
import { formatMoney, formatDateTime } from '@/lib/utils/format';
import { EmptyState, LoadingState, ErrorState } from '@/components/states/page-state';
import type { Transaction } from '@/types/transaction';

const MONTHS_OPTIONS = [3, 6, 12, 24] as const;

function PurchaseBadge({ tx }: { tx: Transaction }) {
  if (tx.is_deferred_purchase) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
        <CreditCard className="size-3" />
        Кредит
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
      <ShoppingCart className="size-3" />
      Наличные
    </span>
  );
}

function DeferredProgress({ tx }: { tx: Transaction }) {
  if (!tx.is_deferred_purchase || tx.deferred_remaining_amount === undefined) return null;

  const remaining = tx.deferred_remaining_amount ?? 0;
  const total = tx.amount;
  const paid = total - remaining;
  const pct = total > 0 ? Math.round((paid / total) * 100) : 0;

  return (
    <div className="mt-1">
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>Выплачено {pct}%</span>
        <span>Остаток {formatMoney(remaining)}</span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="h-full rounded-full bg-blue-400 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function LargePurchasesPage() {
  const [months, setMonths] = useState<(typeof MONTHS_OPTIONS)[number]>(6);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['large-purchases', months],
    queryFn: () => getLargePurchases(months),
    staleTime: 1000 * 60 * 2,
  });

  const transactions = data?.transactions ?? [];
  const totalAmount = data?.total_amount ?? 0;

  const deferred = transactions.filter((t) => t.is_deferred_purchase);
  const largeCash = transactions.filter((t) => t.is_large_purchase && !t.is_deferred_purchase);

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-2xl bg-slate-100">
            <ShoppingCart className="size-5 text-slate-600" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">Крупные покупки</h1>
            <p className="text-sm text-slate-500">Покупки, вынесенные из средних расходов</p>
          </div>
        </div>

        {/* Period selector */}
        <div className="flex gap-1 rounded-xl bg-slate-100 p-1">
          {MONTHS_OPTIONS.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMonths(m)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                months === m
                  ? 'bg-white text-slate-900 shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {m} мес.
            </button>
          ))}
        </div>
      </div>

      {/* Summary cards */}
      {!isLoading && !isError && (
        <div className="mb-6 grid grid-cols-3 gap-3">
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Итого</p>
            <p className="mt-1 text-lg font-bold text-slate-900">{formatMoney(totalAmount)}</p>
            <p className="text-xs text-slate-400">{transactions.length} покупок</p>
          </div>
          <div className="rounded-2xl border border-blue-100 bg-blue-50 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-blue-400">Кредитные</p>
            <p className="mt-1 text-lg font-bold text-blue-800">
              {formatMoney(deferred.reduce((s, t) => s + t.amount, 0))}
            </p>
            <p className="text-xs text-blue-400">{deferred.length} штук</p>
          </div>
          <div className="rounded-2xl border border-amber-100 bg-amber-50 p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-amber-500">Наличные</p>
            <p className="mt-1 text-lg font-bold text-amber-800">
              {formatMoney(largeCash.reduce((s, t) => s + t.amount, 0))}
            </p>
            <p className="text-xs text-amber-400">{largeCash.length} штук</p>
          </div>
        </div>
      )}

      {/* Content */}
      {isLoading && <LoadingState title="Загружаем крупные покупки..." />}
      {isError && <ErrorState title="Ошибка загрузки" description="Не удалось загрузить данные. Попробуйте обновить страницу." />}

      {!isLoading && !isError && transactions.length === 0 && (
        <EmptyState
          title="Крупных покупок нет"
          description={`За последние ${months} месяцев не найдено покупок, помеченных как крупные.`}
        />
      )}

      {!isLoading && !isError && transactions.length > 0 && (
        <div className="space-y-2">
          {transactions.map((tx) => (
            <div
              key={tx.id}
              className="rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-slate-300"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <PurchaseBadge tx={tx} />
                    <span className="truncate text-sm font-medium text-slate-800">
                      {tx.description ?? '—'}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-400">
                    {formatDateTime(tx.transaction_date)}
                  </p>
                  <DeferredProgress tx={tx} />
                </div>
                <div className="shrink-0 text-right">
                  <p className="text-base font-semibold text-slate-900">
                    {formatMoney(tx.amount, tx.currency)}
                  </p>
                  {tx.is_deferred_purchase && (
                    <p className="flex items-center justify-end gap-1 text-xs text-slate-400">
                      <TrendingDown className="size-3" />
                      Выплачивается
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
