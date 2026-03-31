'use client';

import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { SavingsRateMetric } from '@/types/metrics';

// ── Helpers ───────────────────────────────────────────────────────────────────

function barColor(pct: number): string {
  if (pct >= 20) return 'bg-emerald-500';
  if (pct >= 10) return 'bg-amber-400';
  return 'bg-slate-300';
}

function textColor(pct: number): string {
  if (pct >= 20) return 'text-emerald-600';
  if (pct >= 10) return 'text-amber-600';
  return 'text-slate-500';
}

// ── Component ─────────────────────────────────────────────────────────────────

type Props = {
  data: SavingsRateMetric | null | undefined;
  isLoading?: boolean;
};

export function SavingsRateWidget({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <div className="space-y-2">
        <div className="h-7 w-16 animate-pulse rounded bg-slate-100" />
        <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
        <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
      </div>
    );
  }

  if (!data || data.total_income === 0) {
    return (
      <div className="space-y-1">
        <p className="text-xl font-semibold text-slate-400">—</p>
        <p className="text-xs text-slate-400">Нет данных за месяц</p>
      </div>
    );
  }

  const barWidth = Math.min(data.percent, 100);

  return (
    <div className="space-y-2">
      <p className={cn('text-2xl font-bold tabular-nums', textColor(data.percent))}>
        {data.percent.toFixed(0)}%
      </p>

      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={cn('h-full rounded-full transition-all', barColor(data.percent))}
          style={{ width: `${barWidth}%` }}
        />
      </div>

      <div className="mt-1 space-y-1 text-xs text-slate-500">
        <div className="flex justify-between gap-2">
          <span>Инвестировано</span>
          <span className="font-medium text-slate-700">{formatMoney(data.invested)}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span>От дохода</span>
          <span className="font-medium text-slate-700">{formatMoney(data.total_income)}</span>
        </div>
      </div>
    </div>
  );
}
