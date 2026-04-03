'use client';

import { FinancialHealthCard } from '@/components/dashboard/financial-health-card';
import { fiTone } from '@/components/dashboard/card-tones';
import { LinearProgressBar } from '@/components/ui/linear-progress-bar';
import { formatMoney } from '@/lib/utils/format';
import type { FinancialHealth } from '@/types/financial-health';

export function FIPercentCard({
  health,
  isExpanded,
  onToggle,
}: {
  health: FinancialHealth;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const progressColor =
    health.fi_percent < 10
      ? '#E24B4A'
      : health.fi_percent < 50
        ? '#EF9F27'
        : health.fi_percent < 100
          ? '#1D9E75'
          : '#0F6E56';

  return (
    <FinancialHealthCard
      title="Финансовая независимость"
      value={`${health.fi_percent.toFixed(1)}%`}
      zone={fiTone(health.fi_zone)}
      isExpanded={isExpanded}
      onToggle={onToggle}
      collapsedContent={<LinearProgressBar value={health.fi_percent} tone={progressColor} />}
      expandedContent={
        <div className="space-y-2 text-sm text-slate-600">
          <p>Пассивный доход сейчас: <span className="font-medium text-slate-900">{formatMoney(health.fi_passive_income)}</span></p>
          <p>Капитал по правилу 25x: <span className="font-medium text-slate-900">{formatMoney(health.fi_capital_needed)}</span></p>
          <p>Чем ближе показатель к 100%, тем меньше зависимость от активного дохода.</p>
        </div>
      }
    />
  );
}