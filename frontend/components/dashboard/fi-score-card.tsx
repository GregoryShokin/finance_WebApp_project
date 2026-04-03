'use client';

import { FinancialHealthCard } from '@/components/dashboard/financial-health-card';
import { fiScoreTone } from '@/components/dashboard/card-tones';
import type { FinancialHealth } from '@/types/financial-health';

const labels: Record<string, string> = {
  savings_rate: 'Норма сбережений',
  discipline: 'Дисциплина',
  financial_independence: 'Независимость',
  capital_growth: 'Рост капитала',
  dti_inverse: 'Нагрузка',
};

export function FIScoreCard({
  health,
  isExpanded,
  onToggle,
}: {
  health: FinancialHealth;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const history = health.fi_score_components.history;
  const componentEntries = Object.entries(health.fi_score_components).filter(([key]) => key in labels);

  return (
    <FinancialHealthCard
      title="FI-score"
      value={health.fi_score.toFixed(1)}
      zone={fiScoreTone(health.fi_score_zone)}
      isExpanded={isExpanded}
      onToggle={onToggle}
      expandedContent={
        <div className="space-y-3 text-sm text-slate-600">
          <div className="space-y-2">
            {componentEntries.map(([key, value]) => (
              <div key={key}>
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span>{labels[key]}</span>
                  <span className="font-medium text-slate-900">{Number(value).toFixed(1)} / 10</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div className="h-full rounded-full bg-sky-500" style={{ width: `${Math.min(100, Number(value) * 10)}%` }} />
                </div>
              </div>
            ))}
          </div>
          {history ? (
            <div className="grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
              <div className="rounded-2xl bg-slate-50 p-3">База: <span className="font-semibold text-slate-900">{history.baseline.toFixed(1)}</span></div>
              <div className="rounded-2xl bg-slate-50 p-3">Прошлый: <span className="font-semibold text-slate-900">{history.previous.toFixed(1)}</span></div>
              <div className="rounded-2xl bg-slate-50 p-3">Сейчас: <span className="font-semibold text-slate-900">{history.current.toFixed(1)}</span></div>
            </div>
          ) : null}
        </div>
      }
    />
  );
}