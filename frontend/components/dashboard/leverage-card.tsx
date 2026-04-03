'use client';

import { FinancialHealthCard } from '@/components/dashboard/financial-health-card';
import { leverageTone } from '@/components/dashboard/card-tones';
import { GaugeChart } from '@/components/ui/gauge-chart';
import { formatMoney } from '@/lib/utils/format';
import type { FinancialHealth } from '@/types/financial-health';

export function LeverageCard({
  health,
  isExpanded,
  onToggle,
}: {
  health: FinancialHealth;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const tone = leverageTone(health.leverage_zone);
  const gaugeColor = health.leverage < 50 ? '#1D9E75' : health.leverage <= 100 ? '#EF9F27' : '#E24B4A';

  return (
    <FinancialHealthCard
      title="Закредитованность"
      value={`${health.leverage.toFixed(1)}%`}
      zone={tone}
      isExpanded={isExpanded}
      onToggle={onToggle}
      collapsedContent={<GaugeChart value={Math.min(health.leverage, 100)} tone={gaugeColor} label="долг к капиталу" />}
      expandedContent={
        <div className="space-y-3">
          <GaugeChart value={Math.min(health.leverage, 100)} tone={gaugeColor} label="долг к капиталу" />
          <div className="grid gap-2 text-sm text-slate-600 sm:grid-cols-2">
            <div className="rounded-2xl bg-slate-50 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-400">Общий долг</p>
              <p className="mt-1 font-medium text-slate-900">{formatMoney(health.leverage_total_debt)}</p>
            </div>
            <div className="rounded-2xl bg-slate-50 p-3">
              <p className="text-xs uppercase tracking-wide text-slate-400">Собственный капитал</p>
              <p className="mt-1 font-medium text-slate-900">{formatMoney(health.leverage_own_capital)}</p>
            </div>
          </div>
        </div>
      }
    />
  );
}