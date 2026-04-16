'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getExpenseAnalytics, type CategoryExpense } from '@/lib/api/analytics';

function formatMoney(value: number): string {
  return Math.abs(value).toLocaleString('ru-RU', { maximumFractionDigits: 0 }) + ' \u20BD';
}

type ViewMode = 'all' | 'regular' | 'irregular';

function CategoryRow({ cat }: { cat: CategoryExpense }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center justify-between">
        <span className="text-sm text-slate-700">{cat.category_name}</span>
        <span className="text-sm font-medium text-slate-900">{formatMoney(Number(cat.amount))}</span>
      </div>
      {cat.installment_details && cat.installment_details.length > 0 ? (
        <div className="ml-4 text-xs text-slate-400">
          <span className="mr-1">\u2514</span>
          {cat.installment_details.map((d, i) => (
            <span key={i}>
              {i > 0 ? ', ' : ''}
              {d.description} {formatMoney(Number(d.monthly_payment))}{'/мес (ещё '}{d.remaining_months}{' мес)'}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ExpenseAnalyticsWidget() {
  const now = new Date();
  const [year] = useState(now.getFullYear());
  const [month] = useState(now.getMonth() + 1);
  const [viewMode, setViewMode] = useState<ViewMode>('all');

  const { data, isLoading } = useQuery({
    queryKey: ['analytics', 'expenses', year, month],
    queryFn: () => getExpenseAnalytics(year, month),
  });

  if (isLoading) {
    return (
      <div className="h-48 animate-pulse rounded-xl border border-slate-200 bg-slate-50" />
    );
  }

  if (!data) return null;

  const filtered =
    viewMode === 'regular'
      ? data.categories.filter((c) => c.is_regular)
      : viewMode === 'irregular'
        ? data.categories.filter((c) => !c.is_regular)
        : data.categories;

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3">
        <div className="flex items-baseline gap-3">
          <h4 className="text-lg font-bold text-slate-900">
            {'Расходы: '}{formatMoney(Number(data.total_expenses))}
          </h4>
        </div>
        {Number(data.new_installment_obligations) > 0 ? (
          <p className="mt-0.5 text-sm text-slate-400">
            {'Новые обязательства (рассрочки): '}{formatMoney(Number(data.new_installment_obligations))}
          </p>
        ) : null}
      </div>

      <div className="mb-3 flex gap-2">
        {(['all', 'regular', 'irregular'] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => setViewMode(mode)}
            className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
              viewMode === mode
                ? 'bg-slate-900 text-white'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {mode === 'all' ? '\u0412\u0441\u0435' : mode === 'regular' ? '\u0420\u0435\u0433\u0443\u043B\u044F\u0440\u043D\u044B\u0435' : '\u041D\u0435\u0440\u0435\u0433\u0443\u043B\u044F\u0440\u043D\u044B\u0435'}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {filtered.length > 0 ? (
          filtered.map((cat, i) => <CategoryRow key={cat.category_id ?? i} cat={cat} />)
        ) : (
          <p className="text-sm text-slate-400">Нет расходов</p>
        )}
      </div>

      {viewMode === 'all' && data.categories.length > 0 ? (
        <div className="mt-3 flex gap-4 border-t border-slate-100 pt-3 text-xs text-slate-500">
          <span>{'Регулярные: '}{formatMoney(Number(data.regular_expenses))}</span>
          <span>{'Нерегулярные: '}{formatMoney(Number(data.irregular_expenses))}</span>
        </div>
      ) : null}
    </div>
  );
}
