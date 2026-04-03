'use client';

import { FinancialHealthCard } from '@/components/dashboard/financial-health-card';
import { formatMoney } from '@/lib/utils/format';
import type { GoalWithProgress } from '@/types/goal';
import type { HealthCardTone } from '@/types/financial-health';

export function MonthlyAvgBalanceCard({
  monthlyAvgBalance,
  monthsCalculated,
  goals,
  isExpanded,
  onToggle,
}: {
  monthlyAvgBalance: number;
  monthsCalculated: number;
  goals: GoalWithProgress[];
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const tone: HealthCardTone = monthlyAvgBalance >= 0 ? 'good' : monthlyAvgBalance >= -10000 ? 'warning' : 'danger';
  const topGoals = goals.slice(0, 3);

  return (
    <FinancialHealthCard
      title="Среднемесячный остаток"
      value={formatMoney(monthlyAvgBalance)}
      zone={tone}
      isExpanded={isExpanded}
      onToggle={onToggle}
      expandedContent={
        <div className="space-y-3 text-sm text-slate-600">
          <p>Расчёт выполнен за {monthsCalculated} мес.</p>
          {topGoals.length === 0 ? (
            <p>Активных целей пока нет.</p>
          ) : (
            <div className="space-y-2">
              {topGoals.map((goal) => (
                <div key={goal.id} className="rounded-2xl bg-slate-50 p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium text-slate-800">{goal.name}</span>
                    <span className="text-xs text-slate-400">{goal.percent.toFixed(0)}%</span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Осталось {formatMoney(goal.remaining)}
                    {goal.monthly_needed !== null ? ` · темп ${formatMoney(goal.monthly_needed)} / мес.` : ''}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      }
    />
  );
}