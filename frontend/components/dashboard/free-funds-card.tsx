'use client';

import { FinancialHealthCard } from '@/components/dashboard/financial-health-card';
import { formatMoney } from '@/lib/utils/format';
import type { FinancialHealth } from '@/types/financial-health';

export function FreeFundsCard({
  health,
  isExpanded,
  onToggle,
}: {
  health: FinancialHealth;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const zone = health.daily_limit_with_carry > 0 ? 'good' : health.daily_limit === 0 ? 'warning' : 'danger';

  return (
    <FinancialHealthCard
      title="Свободные средства"
      value={formatMoney(health.daily_limit_with_carry)}
      zone={zone}
      isExpanded={isExpanded}
      onToggle={onToggle}
      expandedContent={
        <div className="space-y-2 text-sm text-slate-600">
          <p>Базовый лимит на день: <span className="font-medium text-slate-900">{formatMoney(health.daily_limit)}</span></p>
          <p>С переносом на сегодня: <span className="font-medium text-slate-900">{formatMoney(health.daily_limit_with_carry)}</span></p>
          <p>Перенесено: <span className="font-medium text-slate-900">{health.carry_over_days.toFixed(1)} дня</span></p>
        </div>
      }
    />
  );
}