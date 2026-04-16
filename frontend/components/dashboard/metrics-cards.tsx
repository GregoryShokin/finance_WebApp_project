'use client';

import { useQuery } from '@tanstack/react-query';
import { getMetricsSummary, type MetricsSummary } from '@/lib/api/metrics';
import { Card } from '@/components/ui/card';

function formatMoney(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
  return value < 0 ? `\u2212${formatted} \u20BD` : `${formatted} \u20BD`;
}

function formatSignedMoney(value: number): string {
  const abs = Math.abs(value);
  const formatted = abs.toLocaleString('ru-RU', { maximumFractionDigits: 0 });
  if (value > 0) return `+${formatted} \u20BD`;
  if (value < 0) return `\u2212${formatted} \u20BD`;
  return `${formatted} \u20BD`;
}

function getZoneBadge(zone: string | null): { label: string; className: string } | null {
  switch (zone) {
    case 'healthy':
    case 'normal':
      return { label: 'В норме', className: 'bg-emerald-100 text-emerald-700' };
    case 'excellent':
      return { label: 'Отлично', className: 'bg-emerald-100 text-emerald-700' };
    case 'tight':
    case 'acceptable':
    case 'minimum':
      return { label: 'Допустимо', className: 'bg-amber-100 text-amber-700' };
    case 'deficit':
    case 'danger':
      return { label: 'Внимание', className: 'bg-rose-100 text-rose-700' };
    case 'critical':
      return { label: 'Критично', className: 'bg-rose-100 text-rose-700' };
    default:
      return null;
  }
}

function TrendArrow({ value }: { value: number | null }) {
  if (value == null) return null;
  const arrow = value > 0 ? '\u2191' : value < 0 ? '\u2193' : '';
  const color = value > 0 ? 'text-emerald-600' : value < 0 ? 'text-rose-600' : 'text-slate-400';
  return (
    <span className={`text-xs font-medium ${color}`}>
      {arrow} {formatMoney(Math.abs(value))}
    </span>
  );
}

function FiScoreBadge({ score }: { score: number }) {
  let color = 'text-rose-600 bg-rose-50 border-rose-200';
  if (score >= 8) color = 'text-emerald-700 bg-emerald-50 border-emerald-200';
  else if (score >= 6) color = 'text-green-700 bg-green-50 border-green-200';
  else if (score >= 3) color = 'text-amber-700 bg-amber-50 border-amber-200';

  return (
    <div className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 ${color}`}>
      <span className="text-sm font-medium">FI-score</span>
      <span className="text-lg font-bold">{score.toFixed(1)}</span>
      <span className="text-xs opacity-60">/ 10</span>
    </div>
  );
}

export function MetricsCards() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['metrics', 'summary'],
    queryFn: getMetricsSummary,
  });

  if (isLoading) {
    return (
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-950">Метрики</h3>
            <p className="mt-1 text-sm text-slate-500">Ключевые показатели финансового здоровья.</p>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="p-5">
              <div className="space-y-2">
                <div className="h-4 w-20 animate-pulse rounded bg-slate-100" />
                <div className="h-8 w-32 animate-pulse rounded bg-slate-100" />
                <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
              </div>
            </Card>
          ))}
        </div>
      </section>
    );
  }

  if (isError || !data) return null;

  const { flow, dti, reserve, fi_score } = data;

  const flowBadge = getZoneBadge(flow.zone);
  const dtiBadge = getZoneBadge(dti.zone);
  const reserveBadge = getZoneBadge(reserve.zone);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">Метрики</h3>
          <p className="mt-1 text-sm text-slate-500">Ключевые показатели финансового здоровья.</p>
        </div>
        <FiScoreBadge score={fi_score} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {/* Поток */}
        <Card className="p-5">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-slate-500">Поток</p>
            <TrendArrow value={flow.trend != null ? Number(flow.trend) : null} />
          </div>
          <p className="mt-2 text-2xl font-semibold text-slate-900 lg:text-3xl">
            {formatSignedMoney(Number(flow.basic_flow))}
          </p>
          <div className="mt-3 flex items-center gap-2">
            {flowBadge ? (
              <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${flowBadge.className}`}>
                {flowBadge.label}
              </span>
            ) : null}
            <span className="text-xs text-slate-400">
              Полный: {formatMoney(Number(flow.full_flow))}
            </span>
          </div>
        </Card>

        {/* Нагрузка (DTI) */}
        <Card className="p-5">
          <p className="text-sm font-medium text-slate-500">Нагрузка</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 lg:text-3xl">
            {dti.dti_percent != null ? `${dti.dti_percent.toFixed(0)}%` : '\u2014'}
          </p>
          <div className="mt-3 flex items-center gap-2">
            {dtiBadge ? (
              <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${dtiBadge.className}`}>
                {dtiBadge.label}
              </span>
            ) : null}
            {dti.monthly_payments > 0 ? (
              <span className="text-xs text-slate-400">
                {formatMoney(Number(dti.monthly_payments))} из {formatMoney(Number(dti.regular_income))}
              </span>
            ) : null}
          </div>
        </Card>

        {/* Запас */}
        <Card className="p-5">
          <p className="text-sm font-medium text-slate-500">Запас</p>
          <p className="mt-2 text-2xl font-semibold text-slate-900 lg:text-3xl">
            {reserve.months != null ? `${reserve.months.toFixed(1)} мес.` : '\u2014'}
          </p>
          <div className="mt-3 flex items-center gap-2">
            {reserveBadge ? (
              <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${reserveBadge.className}`}>
                {reserveBadge.label}
              </span>
            ) : null}
            <span className="text-xs text-slate-400">
              {formatMoney(Number(reserve.available_cash))} доступно
            </span>
          </div>
        </Card>
      </div>
    </section>
  );
}
