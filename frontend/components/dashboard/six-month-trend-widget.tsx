'use client';

import { useEffect, useMemo, useState } from 'react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import type { TooltipProps } from 'recharts';

import { MoneyAmount } from '@/components/shared/money-amount';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { Transaction } from '@/types/transaction';

import {
  buildTotals,
  getSixMonthTrendMetrics,
  MONTH_OPTIONS,
  normalizeSlices,
  parseMonthKey,
  type ViewMode,
  VIEW_MODES,
} from '@/components/dashboard/six-month-trend-data';


type Props = {
  transactions: Transaction[];
  isLoading?: boolean;
};

function renderPieTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || payload.length === 0) return null;
  const item = payload[0];
  const rawValue = Number(item.payload?.rawValue ?? 0);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 py-2 shadow-lg">
      <p className="text-sm font-medium text-slate-900">{item.name ?? 'Сегмент'}</p>
      <p className="mt-1 text-sm text-slate-500">{formatMoney(rawValue)}</p>
    </div>
  );
}

export function SixMonthTrendWidget({ transactions, isLoading = false }: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('average');
  const [selectedYear, setSelectedYear] = useState<number>(new Date().getFullYear());
  const [selectedMonthKey, setSelectedMonthKey] = useState<string>('');

  const metrics = useMemo(() => getSixMonthTrendMetrics(transactions), [transactions]);

  useEffect(() => {
    if (!metrics || metrics.availableYears.length === 0) return;
    if (!metrics.availableYears.includes(selectedYear)) {
      setSelectedYear(metrics.availableYears[0]);
    }
  }, [metrics, selectedYear]);

  useEffect(() => {
    if (!metrics || metrics.availableMonthOptions.length === 0) return;
    if (viewMode !== 'month') return;

    const selectedOption = metrics.availableMonthOptions.find((option) => option.key === selectedMonthKey);
    if (selectedOption?.year === selectedYear) return;

    const monthsForYear = metrics.availableMonthOptions.filter((option) => option.year === selectedYear);
    if (monthsForYear.length > 0) {
      setSelectedMonthKey(monthsForYear[monthsForYear.length - 1].key);
    }
  }, [metrics, selectedMonthKey, selectedYear, viewMode]);

  useEffect(() => {
    if (!metrics || metrics.availableMonthOptions.length === 0) return;
    if (!selectedMonthKey || !metrics.availableMonthOptions.some((option) => option.key === selectedMonthKey)) {
      setSelectedMonthKey(metrics.availableMonthOptions[metrics.availableMonthOptions.length - 1].key);
    }
  }, [metrics, selectedMonthKey]);

  const monthsForSelectedYear = (metrics?.availableMonthOptions ?? []).filter((option) => option.year === selectedYear);
  const selectedMonthPoint = metrics?.chartData.find((point) => point.key === selectedMonthKey);
  const selectedMonthTotals = selectedMonthPoint
    ? { income: selectedMonthPoint.income, expense: selectedMonthPoint.expense, creditPayments: selectedMonthPoint.creditPayments, balance: selectedMonthPoint.balance }
    : buildTotals(0, 0);
  const activeTotals = viewMode === 'month' ? selectedMonthTotals : metrics?.sixMonthAverageTotals ?? buildTotals(0, 0);
  const activeSlices = viewMode === 'month'
    ? normalizeSlices(selectedMonthTotals.income, selectedMonthTotals.expense, selectedMonthTotals.creditPayments, selectedMonthTotals.balance)
    : metrics
      ? normalizeSlices(metrics.sixMonthAverageTotals.income, metrics.sixMonthAverageTotals.expense, metrics.sixMonthAverageTotals.creditPayments, metrics.sixMonthAverageTotals.balance)
      : [];

  function renderControls() {
    return (
      <div className="mt-4 space-y-3">
        <div className="inline-flex rounded-full bg-slate-100 p-1 text-xs text-slate-500">
          {VIEW_MODES.map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => setViewMode(option.key)}
              className={cn(
                'rounded-full px-3 py-1.5 transition',
                viewMode === option.key ? 'bg-white text-slate-900 shadow-sm' : 'hover:text-slate-700',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        {viewMode === 'month' ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="relative block">
              <select
                value={String(selectedYear)}
                onChange={(event) => setSelectedYear(Number(event.target.value))}
                className="h-10 w-full appearance-none rounded-2xl border border-slate-200 bg-slate-50 px-4 pr-9 text-sm text-slate-700 outline-none transition focus:border-slate-400"
              >
                {(metrics?.availableYears ?? []).map((year) => (
                  <option key={year} value={year}>{year}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">▼</span>
            </label>

            <label className="relative block">
              <select
                value={selectedMonthKey}
                onChange={(event) => {
                  setSelectedMonthKey(event.target.value);
                  const parsed = parseMonthKey(event.target.value);
                  if (parsed.year) {
                    setSelectedYear(parsed.year);
                  }
                }}
                className="h-10 w-full appearance-none rounded-2xl border border-slate-200 bg-slate-50 px-4 pr-9 text-sm text-slate-700 outline-none transition focus:border-slate-400"
              >
                {monthsForSelectedYear.map((option) => (
                  <option key={option.key} value={option.key}>{MONTH_OPTIONS[option.monthIndex]}</option>
                ))}
              </select>
              <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">▼</span>
            </label>
          </div>
        ) : null}
      </div>
    );
  }

  function renderValueBlocks() {
    return (
      <div className="mt-4 space-y-3">
        <div className="flex items-center gap-2">
          <span className="size-2.5 shrink-0 rounded-full bg-cyan-500" />
          <div>
            <p className="text-xs text-slate-500">Доходы</p>
            <p className="text-sm font-bold text-cyan-600">{formatMoney(activeTotals.income)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="size-2.5 shrink-0 rounded-full bg-rose-500" />
          <div>
            <p className="text-xs text-slate-500">Расходы</p>
            <p className="text-sm font-bold text-rose-600">{formatMoney(activeTotals.expense)}</p>
          </div>
        </div>
        {activeTotals.creditPayments > 0 ? (
          <div className="flex items-center gap-2">
            <span className="size-2.5 shrink-0 rounded-full bg-slate-400" />
            <div>
              <p className="text-xs text-slate-500">Кредиты</p>
              <p className="text-sm font-bold text-slate-500">{formatMoney(activeTotals.creditPayments)}</p>
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <Card className="h-full p-4 lg:p-5">
      {isLoading ? (
        <>
          <p className="text-sm font-semibold text-slate-900">Динамика за 6 месяцев</p>
          <div className="mt-4 h-52 animate-pulse rounded-[28px] bg-slate-50" />
        </>
      ) : !metrics ? (
        <>
          <p className="text-sm font-semibold text-slate-900">Динамика за 6 месяцев</p>
          <div className="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-500">
            Недостаточно данных для построения динамики.
          </div>
        </>
      ) : (
        <>
          <h4 className="text-base font-semibold text-slate-900">Динамика за 6 месяцев</h4>
          {renderControls()}
          {renderValueBlocks()}

          <div className="mt-5 h-[290px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={activeSlices}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={70}
                  outerRadius={128}
                  paddingAngle={1.5}
                  stroke="none"
                >
                  {activeSlices.map((entry) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip content={renderPieTooltip} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </Card>
  );
}
