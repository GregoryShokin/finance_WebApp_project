'use client';

import { useQuery } from '@tanstack/react-query';
import { getHealthSummary, type HealthSummary } from '@/lib/api/metrics';

const FI_ZONE_LABELS: Record<string, string> = {
  risk: '\u0420\u0438\u0441\u043A',
  growth: '\u0420\u043E\u0441\u0442',
  path: '\u041F\u0443\u0442\u044C',
  freedom: '\u0421\u0432\u043E\u0431\u043E\u0434\u0430',
};

const FI_ZONE_COLORS: Record<string, string> = {
  risk: 'text-red-600 bg-red-50 border-red-200',
  growth: 'text-yellow-700 bg-yellow-50 border-yellow-200',
  path: 'text-green-700 bg-green-50 border-green-200',
  freedom: 'text-emerald-700 bg-emerald-50 border-emerald-200',
};

const METRIC_LABELS: Record<string, string> = {
  flow: '\u041F\u043E\u0442\u043E\u043A',
  capital: '\u041B\u0438\u043A\u0432\u0438\u0434\u043D\u044B\u0439 \u043A\u0430\u043F\u0438\u0442\u0430\u043B',
  dti: '\u041D\u0430\u0433\u0440\u0443\u0437\u043A\u0430',
  reserve: '\u0417\u0430\u043F\u0430\u0441',
};

const ZONE_PRIORITY: Record<string, number> = {
  critical: 0, deficit: 1, danger: 1, minimum: 2, tight: 2,
  acceptable: 3, normal: 4, healthy: 5, green: 5, excellent: 6,
};

function getBarColor(zone: string): string {
  const p = ZONE_PRIORITY[zone] ?? 5;
  if (p <= 1) return 'bg-red-500';
  if (p <= 2) return 'bg-yellow-500';
  if (p <= 3) return 'bg-yellow-400';
  return 'bg-green-500';
}

function normalizeScore(metric: string, data: HealthSummary): number {
  const { flow, capital, dti, reserve } = data.metrics;
  if (metric === 'flow') {
    const li = flow.lifestyle_indicator;
    if (li == null) return 50;
    return Math.max(0, Math.min(100, (li / 20) * 100));
  }
  if (metric === 'capital') {
    if (capital.trend == null) return 50;
    return capital.trend > 0 ? 75 : 25;
  }
  if (metric === 'dti') {
    const p = dti.dti_percent;
    if (p == null) return 100;
    return Math.max(0, Math.min(100, (1 - p / 60) * 100));
  }
  if (metric === 'reserve') {
    const m = reserve.months;
    if (m == null) return 0;
    return Math.max(0, Math.min(100, (m / 6) * 100));
  }
  return 50;
}

function getMetricZone(metric: string, data: HealthSummary): string {
  const { flow, capital, dti, reserve } = data.metrics;
  if (metric === 'flow') return flow.zone;
  if (metric === 'capital') {
    if (capital.trend == null) return 'normal';
    return capital.trend > 0 ? 'green' : 'danger';
  }
  if (metric === 'dti') return dti.zone ?? 'normal';
  if (metric === 'reserve') return reserve.zone ?? 'normal';
  return 'normal';
}

const SEVERITY_STYLES: Record<string, string> = {
  alert: 'border-l-4 border-l-red-500 bg-red-50',
  warning: 'border-l-4 border-l-yellow-500 bg-yellow-50',
  info: 'border-l-4 border-l-blue-500 bg-blue-50',
};

function getSeverity(zone: string): string {
  const p = ZONE_PRIORITY[zone] ?? 5;
  if (p <= 1) return 'alert';
  if (p <= 3) return 'warning';
  return 'info';
}

export function MetricsHealthSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['metrics', 'health'],
    queryFn: getHealthSummary,
  });

  if (isLoading) {
    return <div className="h-64 animate-pulse rounded-3xl border border-slate-200 bg-slate-50" />;
  }

  if (isError || !data) return null;

  const fiColor = FI_ZONE_COLORS[data.fi_zone] ?? FI_ZONE_COLORS.risk;
  const fiLabel = FI_ZONE_LABELS[data.fi_zone] ?? '\u0420\u0438\u0441\u043A';

  const metrics = ['flow', 'capital', 'dti', 'reserve'] as const;
  const lifeStyle = data.metrics.flow.lifestyle_indicator;

  return (
    <div className="space-y-6">
      {/* FI-score */}
      <div className={`flex items-center gap-4 rounded-2xl border p-5 ${fiColor}`}>
        <div className="text-4xl font-bold">{data.fi_score.toFixed(1)}</div>
        <div>
          <div className="text-sm font-medium opacity-70">FI-score</div>
          <div className="text-lg font-semibold">{fiLabel}</div>
        </div>
      </div>

      {/* Four metric bars */}
      <div className="space-y-3">
        {metrics.map((m) => {
          const zone = getMetricZone(m, data);
          const pct = normalizeScore(m, data);
          const isWeakest = m === data.weakest_metric;
          return (
            <div
              key={m}
              className={`rounded-xl border p-3 ${isWeakest ? 'border-yellow-300 bg-yellow-50' : 'border-slate-200 bg-white'}`}
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">
                  {METRIC_LABELS[m]}
                  {isWeakest ? (
                    <span className="ml-2 text-xs text-yellow-600">\u0424\u043E\u043A\u0443\u0441</span>
                  ) : null}
                </span>
                <span className="text-xs text-slate-500">{Math.round(pct)}%</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100">
                <div
                  className={`h-2 rounded-full transition-all ${getBarColor(zone)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Lifestyle indicator */}
      {lifeStyle != null ? (
        <div className="rounded-xl border border-slate-200 bg-white p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-slate-600">
              \u0423\u0440\u043E\u0432\u0435\u043D\u044C \u0436\u0438\u0437\u043D\u0438
            </span>
            <span className={`text-sm font-medium ${lifeStyle >= 20 ? 'text-green-600' : lifeStyle >= 0 ? 'text-yellow-600' : 'text-red-600'}`}>
              {lifeStyle.toFixed(1)}%
            </span>
          </div>
          <p className="mt-0.5 text-xs text-slate-400">
            \u0414\u043E\u043B\u044F \u0434\u043E\u0445\u043E\u0434\u0430, \u043E\u0441\u0442\u0430\u044E\u0449\u0430\u044F\u0441\u044F \u043F\u043E\u0441\u043B\u0435 \u0440\u0430\u0441\u0445\u043E\u0434\u043E\u0432 \u0438 \u043A\u0440\u0435\u0434\u0438\u0442\u043E\u0432
          </p>
        </div>
      ) : null}

      {/* Recommendations */}
      {data.recommendations.length > 0 ? (
        <div className="space-y-2">
          <h4 className="text-sm font-semibold text-slate-700">
            \u0427\u0442\u043E \u0434\u0435\u043B\u0430\u0442\u044C
          </h4>
          {data.recommendations.map((rec) => (
            <div
              key={rec.message_key}
              className={`rounded-lg p-3 ${SEVERITY_STYLES[getSeverity(rec.zone)] ?? SEVERITY_STYLES.info}`}
            >
              <div className="text-sm font-medium text-slate-800">{rec.title}</div>
              <p className="mt-0.5 text-xs text-slate-600">{rec.message}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
