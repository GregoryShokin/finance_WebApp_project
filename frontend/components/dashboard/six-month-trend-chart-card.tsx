'use client';

import { useMemo } from 'react';
import { Bar, CartesianGrid, ComposedChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { Card } from '@/components/ui/card';
import { formatMoney } from '@/lib/utils/format';
import type { Transaction } from '@/types/transaction';

import { formatTrendYAxisValue, getSixMonthTrendMetrics, TREND_COLORS } from '@/components/dashboard/six-month-trend-data';


type Props = {
  transactions: Transaction[];
  isLoading?: boolean;
};

export function SixMonthTrendChartCard({ transactions, isLoading = false }: Props) {
  const metrics = useMemo(() => getSixMonthTrendMetrics(transactions), [transactions]);

  return (
    <Card className="p-5 lg:p-6">
      <h4 className="text-base font-semibold text-slate-900">Динамика за 6 месяцев</h4>

      {isLoading ? (
        <div className="mt-5 h-[420px] animate-pulse rounded-[28px] bg-slate-50" />
      ) : !metrics ? (
        <div className="mt-5 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
          Недостаточно данных для построения графика.
        </div>
      ) : (
        <div className="mt-5 h-[420px] rounded-[28px] bg-slate-50/70 px-3 py-4 sm:px-4">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={metrics.chartData} barGap={2} barCategoryGap="8%">
              <CartesianGrid vertical={false} stroke="#E2E8F0" strokeDasharray="3 3" />
              <XAxis dataKey="month" tickLine={false} axisLine={false} tick={{ fill: '#64748B', fontSize: 12 }} />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fill: '#94A3B8', fontSize: 12 }}
                tickFormatter={formatTrendYAxisValue}
                width={52}
              />
              <Tooltip
                cursor={{ fill: 'rgba(148, 163, 184, 0.08)' }}
                formatter={(value: number, name: string) => {
                  if (name === 'income') return [formatMoney(value), 'Доходы'];
                  if (name === 'expense') return [formatMoney(value), 'Расходы'];
                  return [formatMoney(value), 'Остаток'];
                }}
                labelFormatter={(label) => `Месяц: ${label}`}
              />
              <Bar dataKey="income" name="income" fill={TREND_COLORS.chartIncome} radius={[8, 8, 0, 0]} maxBarSize={20} />
              <Bar dataKey="expense" name="expense" fill={TREND_COLORS.chartExpense} radius={[8, 8, 0, 0]} maxBarSize={20} />
              <Bar dataKey="balance" name="balance" fill={TREND_COLORS.chartBalance} radius={[8, 8, 0, 0]} maxBarSize={20} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
