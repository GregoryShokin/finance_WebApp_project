'use client';

import { FinancialHealthCard } from '@/components/dashboard/financial-health-card';
import { savingsTone } from '@/components/dashboard/card-tones';
import type { FinancialHealth } from '@/types/financial-health';

export function SavingsRateCard({
  health,
  isExpanded,
  onToggle,
}: {
  health: FinancialHealth;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <FinancialHealthCard
      title="Норма сбережений"
      value={`${health.savings_rate.toFixed(1)}%`}
      zone={savingsTone(health.savings_rate_zone)}
      isExpanded={isExpanded}
      onToggle={onToggle}
      expandedContent={
        <div className="space-y-2 text-sm text-slate-600">
          <p>Показывает, какая доля дохода остаётся после расходов в текущем месяце.</p>
          <p>Зона: до 10% слабая, 10-20% рабочая, выше 20% сильная.</p>
        </div>
      }
    />
  );
}