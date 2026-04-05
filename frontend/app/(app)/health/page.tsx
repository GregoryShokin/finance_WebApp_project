'use client';

import Link from 'next/link';
import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, CheckCircle2, HeartPulse, Minus, TrendingDown, TrendingUp } from 'lucide-react';

import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, LoadingState } from '@/components/states/page-state';
import { Card } from '@/components/ui/card';
import { useFinancialHealth } from '@/hooks/use-financial-health';
import { getCategories } from '@/lib/api/categories';
import { getGoals } from '@/lib/api/goals';
import { getTransactions } from '@/lib/api/transactions';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { FiScoreZone, MonthlyHealthSnapshot } from '@/types/financial-health';

const COLORS = {
  green: '#1D9E75',
  orange: '#EF9F27',
  red: '#E24B4A',
  blue: '#378ADD',
  lightBlue: '#85B7EB',
  lightRed: '#F09595',
  neutral: '#B4B2A9',
};

const SECTION_CARD = 'rounded-3xl border border-white/60 bg-white/85 p-5 shadow-soft backdrop-blur lg:p-6';

type Tone = 'good' | 'warning' | 'danger' | 'info' | 'neutral';

type ActionStep = {
  key: string;
  title: string;
  href: string;
  lesson: string;
};

function zoneLabel(zone: FiScoreZone) {
  switch (zone) {
    case 'freedom':
      return 'Свобода';
    case 'on_way':
      return 'Путь к свободе';
    case 'growth':
      return 'Рост';
    default:
      return 'Риск';
  }
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function average(values: number[]) {
  if (!values.length) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getToneBadge(tone: Tone) {
  if (tone === 'good') return 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200';
  if (tone === 'warning') return 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200';
  if (tone === 'danger') return 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200';
  if (tone === 'neutral') return 'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200';
  return 'bg-sky-50 text-sky-700 ring-1 ring-inset ring-sky-200';
}

function getSavingsTone(value: number): Tone {
  if (value >= 20) return 'good';
  if (value >= 10) return 'warning';
  return 'danger';
}

function getDtiTone(value: number): Tone {
  if (value < 30) return 'good';
  if (value < 40) return 'warning';
  return 'danger';
}

function getDisciplineTone(value: number | null): Tone {
  if (value === null) return 'neutral';
  if (value >= 90) return 'good';
  if (value >= 75) return 'warning';
  return 'danger';
}

function getFiTone(value: number): Tone {
  if (value >= 100) return 'good';
  if (value >= 50) return 'info';
  if (value >= 10) return 'warning';
  return 'danger';
}

function getHeatmapCellStyle(direction: string, fulfillment: number) {
  if (fulfillment < 0) {
    return { backgroundColor: 'var(--color-background-secondary)', color: 'var(--color-text-tertiary)' };
  }

  const isIncome = direction.startsWith('income');
  if (isIncome) {
    if (fulfillment >= 95) return { backgroundColor: '#EAF3DE', color: '#3B6D11' };
    if (fulfillment >= 70) return { backgroundColor: '#FAEEDA', color: '#854F0B' };
    return { backgroundColor: '#FCEBEB', color: '#A32D2D' };
  }

  if (fulfillment <= 100) return { backgroundColor: '#EAF3DE', color: '#3B6D11' };
  if (fulfillment <= 120) return { backgroundColor: '#FAEEDA', color: '#854F0B' };
  return { backgroundColor: '#FCEBEB', color: '#A32D2D' };
}

function fiScoreBarColor(value: number) {
  if (value >= 8) return COLORS.blue;
  if (value >= 6) return COLORS.green;
  if (value >= 3) return COLORS.orange;
  return COLORS.red;
}

function ProgressRow({ label, value, tone = 'good' }: { label: string; value: number; tone?: Tone }) {
  const width = `${clamp((value / 10) * 100, 0, 100)}%`;
  const fill = tone === 'danger' ? COLORS.red : tone === 'warning' ? COLORS.orange : tone === 'info' ? COLORS.blue : COLORS.green;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-semibold text-slate-900">{value.toFixed(1)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full transition-all" style={{ width, backgroundColor: fill }} />
      </div>
    </div>
  );
}

function MetricBadge({ label, tone }: { label: string; tone: Tone }) {
  return <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', getToneBadge(tone))}>{label}</span>;
}

function MiniBars({
  values,
  colorForValue,
  maxValue,
}: {
  values: number[];
  colorForValue: (value: number, index: number) => string;
  maxValue?: number;
}) {
  const safeValues = values.length ? values : [0];
  const peak = Math.max(maxValue ?? 0, ...safeValues, 1);
  const width = 240;
  const height = 84;
  const gap = 10;
  const barWidth = (width - gap * (safeValues.length - 1)) / safeValues.length;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-24 w-full">
      {safeValues.map((value, index) => {
        const barHeight = peak > 0 ? (Math.max(value, 0) / peak) * (height - 12) : 0;
        const x = index * (barWidth + gap);
        const y = height - barHeight;
        return <rect key={`${index}-${value}`} x={x} y={y} width={barWidth} height={barHeight} rx="8" fill={colorForValue(value, index)} />;
      })}
    </svg>
  );
}

function SavingsMixChart({ history }: { history: MonthlyHealthSnapshot[] }) {
  const width = 560;
  const height = 210;
  const chartTop = 16;
  const chartBottom = 34;
  const chartHeight = height - chartTop - chartBottom;
  const maxY = 70;
  const groupWidth = width / Math.max(history.length, 1);
  const barWidth = Math.min(14, groupWidth / 5);

  const yForRate = (rate: number) => chartTop + chartHeight - (clamp(rate, 0, maxY) / maxY) * chartHeight;
  const targetY = yForRate(20);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full overflow-visible">
      {[0, 20, 40, 60, 70].map((tick) => {
        const y = yForRate(tick);
        return (
          <g key={tick}>
            <line x1="0" y1={y} x2={width} y2={y} stroke="#E2E8F0" strokeDasharray={tick === 20 ? '5 5' : undefined} />
            <text x="0" y={y - 4} fontSize="10" fill="#94A3B8">
              {tick}%
            </text>
          </g>
        );
      })}
      <line x1="0" y1={targetY} x2={width} y2={targetY} stroke={COLORS.green} strokeDasharray="6 4" opacity="0.65" />
      {history.map((item, index) => {
        const center = groupWidth * index + groupWidth / 2;
        const values = [
          { key: 'essential', value: item.essential_rate, color: COLORS.red, offset: -barWidth - 4 },
          { key: 'secondary', value: item.secondary_rate, color: COLORS.orange, offset: 0 },
          { key: 'savings', value: item.savings_rate, color: COLORS.green, offset: barWidth + 4 },
        ];

        return (
          <g key={item.month}>
            {values.map((entry) => {
              const y = yForRate(entry.value);
              return (
                <rect
                  key={entry.key}
                  x={center + entry.offset - barWidth / 2}
                  y={y}
                  width={barWidth}
                  height={chartTop + chartHeight - y}
                  rx="5"
                  fill={entry.color}
                  opacity="0.95"
                />
              );
            })}
            <text x={center} y={height - 8} textAnchor="middle" fontSize="11" fill="#64748B">
              {item.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function RingScore({ score }: { score: number }) {
  const radius = 204;
  const circumference = 2 * Math.PI * radius;
  const progress = clamp((score / 10) * 100, 0, 100);
  const offset = circumference - (progress / 100) * circumference;

  return (
    <svg viewBox="0 0 600 600" className="mx-auto h-[18.75rem] w-[18.75rem] sm:h-[22rem] sm:w-[22rem] xl:h-[25.5rem] xl:w-[25.5rem]">
      <circle cx="300" cy="300" r={radius} fill="none" stroke="#E2E8F0" strokeWidth="32" />
      <circle
        cx="300"
        cy="300"
        r={radius}
        fill="none"
        stroke={fiScoreBarColor(score)}
        strokeWidth="32"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 300 300)"
      />
      <text x="300" y="288" textAnchor="middle" fontSize="92" fontWeight="700" fill="#0F172A">
        {score.toFixed(1)}
      </text>
      <text x="300" y="338" textAnchor="middle" fontSize="28" fill="#64748B">
        из 10
      </text>
    </svg>
  );
}

function formatRublesCompact(value: number) {
  return `${Math.round(value).toLocaleString('ru-RU')} ₽`;
}

export default function HealthPage() {
  const healthQuery = useFinancialHealth();
  const transactionsQuery = useQuery({ queryKey: ['transactions', 'health'], queryFn: () => getTransactions() });
  const categoriesQuery = useQuery({ queryKey: ['categories', 'health'], queryFn: () => getCategories() });
  const goalsQuery = useQuery({ queryKey: ['goals', 'health'], queryFn: getGoals });

  const isLoading = healthQuery.isLoading || transactionsQuery.isLoading || categoriesQuery.isLoading || goalsQuery.isLoading;
  const isError = Boolean(healthQuery.error || transactionsQuery.error || categoriesQuery.error || goalsQuery.error);
  const health = healthQuery.data;

  const metrics = useMemo(() => {
    if (!health) return null;
    const currentHealth = health;

    const transactions = transactionsQuery.data ?? [];
    const categories = categoriesQuery.data ?? [];
    const goals = goalsQuery.data ?? [];
    const history = currentHealth.monthly_history ?? [];
    const safetyGoal = goals.find((goal) => goal.system_key === 'safety_buffer') ?? null;
    const safetyBufferPercent = safetyGoal?.percent ?? 0;

    const componentRows: Array<{ key: string; label: string; value: number; tone: Tone }> = [
      { key: 'savings_rate', label: 'Норма сбережений', value: currentHealth.fi_score_components.savings_rate ?? 0, tone: getSavingsTone((currentHealth.fi_score_components.savings_rate ?? 0) * 2) },
      { key: 'discipline', label: 'Дисциплина', value: currentHealth.fi_score_components.discipline ?? 0, tone: getDisciplineTone(currentHealth.discipline) },
      { key: 'financial_independence', label: 'Финансовая независимость', value: currentHealth.fi_score_components.financial_independence ?? 0, tone: currentHealth.fi_percent >= 50 ? 'good' : 'info' },
      { key: 'safety_buffer', label: 'Подушка безопасности', value: currentHealth.fi_score_components.safety_buffer ?? 0, tone: (currentHealth.fi_score_components.safety_buffer ?? 0) < 5 ? 'warning' : 'good' },
      { key: 'dti_inverse', label: 'Кредитная нагрузка', value: currentHealth.fi_score_components.dti_inverse ?? 0, tone: (currentHealth.fi_score_components.dti_inverse ?? 0) < 5 ? 'warning' : 'good' },
    ];

    const diagnosis = currentHealth.dti > 40
      ? 'Высокая кредитная нагрузка — главный приоритет сейчас.'
      : safetyBufferPercent < 100
        ? 'Ты на правильном пути. Подушка ещё не сформирована.'
        : 'Отличный результат. Пора думать об инвестициях.';

    const historyDti = history.map((item) => item.dti);
    const dtiFirst = historyDti[0] ?? currentHealth.dti;
    const dtiLast = historyDti.at(-1) ?? currentHealth.dti;
    const dtiDelta = dtiLast - dtiFirst;
    const dtiMonths = Math.max(history.length - 1, 1);
    const dtiText = dtiDelta <= -0.5
      ? `Снизилась на ${Math.abs(dtiDelta).toFixed(1)} п.п. за ${dtiMonths} мес. ${dtiLast > 30 ? `Ещё ${(dtiLast - 30).toFixed(1)} п.п. — и зелёная зона.` : 'Ты уже в зелёной зоне.'}`
      : dtiDelta >= 0.5
        ? `Выросла на ${Math.abs(dtiDelta).toFixed(1)} п.п. Обрати внимание на кредитные платежи.`
        : 'Держится рядом с текущим уровнем. Сильного сдвига за последние месяцы не было.';

    const avgIncome = average(history.map((item) => item.income));
    const avgEssential = average(history.map((item) => item.essential));
    const avgSecondary = average(history.map((item) => item.secondary));
    const avgSavings = average(history.map((item) => item.savings));
    const avgEssentialRate = average(history.map((item) => item.essential_rate));
    const avgSecondaryRate = average(history.map((item) => item.secondary_rate));
    const avgSavingsRate = average(history.map((item) => item.savings_rate));

    const categoriesById = new Map(categories.map((category) => [category.id, category]));
    const relevantMonths = new Set(history.map((item) => item.month));
    const secondaryByCategory = new Map<number, { name: string; total: number }>();

    for (const transaction of transactions) {
      if (!transaction.affects_analytics) continue;
      const txMonth = monthKey(new Date(transaction.transaction_date));
      if (!relevantMonths.has(txMonth)) continue;
      const category = transaction.category_id ? categoriesById.get(transaction.category_id) : undefined;

      if (transaction.type === 'expense' && category && category.priority === 'expense_secondary') {
        const current = secondaryByCategory.get(category.id) ?? { name: category.name, total: 0 };
        current.total += Number(transaction.amount);
        secondaryByCategory.set(category.id, current);
      }
    }

    const topSecondary = [...secondaryByCategory.values()]
      .map((entry) => ({ ...entry, average: history.length ? entry.total / history.length : entry.total }))
      .sort((left, right) => right.average - left.average)[0] ?? null;

    const directionOrder = ['income_active', 'income_passive', 'expense_essential', 'expense_secondary'];
    const directionLabels = new Map([
      ['income_active', 'Доходы активные'],
      ['income_passive', 'Доходы пассивные'],
      ['expense_essential', 'Обязательные расходы'],
      ['expense_secondary', 'Второстепенные расходы'],
    ]);
    const disciplineHeatmapRows = directionOrder.map((direction) => ({
      direction,
      label: directionLabels.get(direction) ?? direction,
      values: history.map((month) => month.direction_heatmap.find((item) => item.direction === direction) ?? {
        direction,
        label: directionLabels.get(direction) ?? direction,
        planned: 0,
        actual: 0,
        fulfillment: -1,
      }),
    }));
    const allHeatmapMissing = disciplineHeatmapRows.every((row) => row.values.every((item) => item.fulfillment < 0));
    const chronicUnderperformers = currentHealth.chronic_underperformers ?? [];
    const unplannedCategories = (currentHealth.unplanned_categories ?? []).slice(0, 3);

    const disciplineText = metricsText();

    function metricsText() {
      if (!history.length) {
        return 'Недостаточно данных. Продолжай вносить транзакции.';
      }
      if (allHeatmapMissing) {
        return 'Создай бюджет по категориям для отслеживания дисциплины.';
      }
      const lastMonth = history[history.length - 1];
      const candidates = (lastMonth.direction_heatmap ?? [])
        .filter((item) => item.fulfillment >= 0)
        .map((item) => ({
          ...item,
          severity: item.direction.startsWith('income')
            ? (item.fulfillment < 95 ? 95 - item.fulfillment : 0)
            : (item.fulfillment > 100 ? item.fulfillment - 100 : 0),
        }))
        .filter((item) => item.severity > 0)
        .sort((left, right) => right.severity - left.severity);
      if (candidates.length > 0) {
        const worst = candidates[0];
        const prefix = `В ${lastMonth.label}: ${worst.label.toLowerCase()} выполнено на ${Math.round(worst.fulfillment)}%.`;
        if (currentHealth.discipline_violations.length > 0) {
          const topViolation = currentHealth.discipline_violations[0];
          return `${prefix} Хроническое превышение: ${topViolation.category_name} — ${topViolation.months_count} мес. подряд.`;
        }
        return prefix;
      }
      if (currentHealth.discipline === null) {
        return 'Создай бюджет по категориям, чтобы отслеживать дисциплину.';
      }
      return 'Отлично держишь план по всем направлениям.';
    }

    const savingsGapMonthly = Math.max(0, avgIncome * 0.2 - Math.max(avgSavings, 0));
    const savingsAdvice = currentHealth.avg_savings_rate < 20
      ? topSecondary
        ? `До рекомендуемого минимума не хватает ${(20 - currentHealth.avg_savings_rate).toFixed(1)} п.п. Быстрее всего добрать их через контроль категории «${topSecondary.name}»: в среднем ${formatMoney(topSecondary.average)} в месяц.`
        : `До рекомендуемого минимума не хватает ${(20 - currentHealth.avg_savings_rate).toFixed(1)} п.п. Начни с ревизии второстепенных расходов.`
      : avgSecondaryRate > 30
        ? 'Сбережения уже выше минимума, но второстепенные расходы всё ещё тяжёлые. Их контроль даст больше свободы для целей и инвестиций.'
        : 'Норма сбережений в зелёной зоне. Теперь можно удерживать темп и направлять излишек в долгосрочные цели.';

    const neededToSafety = Math.max(0, safetyGoal?.remaining ?? 0);
    const dtiDeclinePerMonth = dtiDelta < 0 ? Math.abs(dtiDelta) / dtiMonths : 0;
    const monthsToGreen = currentHealth.dti > 30
      ? Math.max(1, dtiDeclinePerMonth > 0 ? Math.ceil((currentHealth.dti - 30) / dtiDeclinePerMonth) : 6)
      : 0;

    const actionSteps: ActionStep[] = [];
    if (safetyBufferPercent < 100) {
      actionSteps.push({
        key: 'safety-buffer',
        title: `Сформируй подушку безопасности — тебе нужно ещё ${formatMoney(neededToSafety)} до минимальной цели.`,
        href: '/planning?lesson=6',
        lesson: 'Урок 6 — Подушка безопасности',
      });
    }
    if (currentHealth.avg_savings_rate < 20) {
      actionSteps.push({
        key: 'savings-rate',
        title: `Подними норму сбережений до 20% — это ${formatMoney(savingsGapMonthly)} в месяц при твоём доходе.`,
        href: '/planning?lesson=3',
        lesson: 'Урок 3 — Норма сбережений',
      });
    }
    if (currentHealth.dti > 30) {
      actionSteps.push({
        key: 'dti',
        title: `Снижай кредитную нагрузку. При текущем темпе выйдешь в зелёную зону через ${monthsToGreen} мес.`,
        href: '/planning?lesson=1',
        lesson: 'Урок 1 — Кредиты и долги',
      });
    }
    if (!actionSteps.length || actionSteps.length < 3) {
      actionSteps.push({
        key: 'invest',
        title: 'Начни инвестировать свободный капитал — подушка сформирована, нагрузка низкая.',
        href: '/planning?lesson=11',
        lesson: 'Урок 11 — Инвестиционный портфель',
      });
    }

    return {
      history,
      safetyBufferPercent,
      diagnosis,
      componentRows,
      dtiText,
      avgIncome,
      avgEssential,
      avgSecondary,
      avgSavings,
      avgEssentialRate,
      avgSecondaryRate,
      avgSavingsRate,
      disciplineHeatmapRows,
      allHeatmapMissing,
      chronicUnderperformers,
      unplannedCategories,
      independenceText: currentHealth.fi_monthly_gap > 0
        ? `Пассивный доход покрывает ${currentHealth.fi_percent.toFixed(1)}% расходов. Не хватает ${Math.round(currentHealth.fi_monthly_gap).toLocaleString('ru-RU')} ₽/мес пассивного дохода.`
        : 'Пассивный доход полностью покрывает расходы. Финансовая свобода достигнута!',
      disciplineText,
      savingsAdvice,
      actionSteps: actionSteps.slice(0, 3),
    };
  }, [categoriesQuery.data, goalsQuery.data, health, transactionsQuery.data]);

  if (isLoading) {
    return (
      <PageShell
        title="Финансовое здоровье"
        description="Динамика ключевых показателей, чтобы видеть не только текущий снимок, но и направление движения."
      >
        <LoadingState title="Собираем динамику" description="Готовим историю по месяцам, траекторию показателей и персональные подсказки." />
      </PageShell>
    );
  }

  if (isError || !health || !metrics) {
    return (
      <PageShell
        title="Финансовое здоровье"
        description="Динамика ключевых показателей, чтобы видеть не только текущий снимок, но и направление движения."
      >
        <ErrorState title="Не удалось загрузить страницу здоровья" description="Проверь доступность API и попробуй открыть страницу ещё раз." />
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Финансовое здоровье"
      description="Динамика и траектория: как меняются сбережения, кредитная нагрузка, дисциплина и движение к финансовой свободе."
    >
      <section className={cn(SECTION_CARD, 'grid gap-8 xl:grid-cols-[1fr_1fr] xl:items-center')}>
        <div className="flex flex-col items-center justify-center">
          <RingScore score={health.fi_score} />
          <div className="mt-5 space-y-3 text-center">
            <div>
              <p className="text-sm uppercase tracking-[0.18em] text-slate-400">Общий пульс</p>
              <h3 className="mt-2 text-4xl font-semibold text-slate-950">{health.fi_score.toFixed(1)}</h3>
            </div>
            <MetricBadge label={zoneLabel(health.fi_score_zone)} tone={health.fi_score >= 8 ? 'info' : health.fi_score >= 6 ? 'good' : health.fi_score >= 3 ? 'warning' : 'danger'} />
            <p className="mx-auto max-w-xl text-sm leading-6 text-slate-600">{metrics.diagnosis}</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <h4 className="text-base font-semibold text-slate-950">Из чего складывается оценка</h4>
            <p className="mt-1 text-sm text-slate-500">Пять компонентов, которые формируют FI-score прямо сейчас.</p>
          </div>
          <div className="space-y-3">
            {metrics.componentRows.map((row) => (
              <ProgressRow key={row.key} label={row.label} value={row.value} tone={row.tone} />
            ))}
          </div>
          <div className="rounded-2xl bg-slate-50/80 p-4">
            <div className="mb-3 flex items-center justify-between text-sm">
              <span className="font-medium text-slate-700">FI-score за 6 месяцев</span>
              <span className="text-slate-400">по завершённым месяцам</span>
            </div>
            <MiniBars
              values={metrics.history.map((item) => item.fi_score)}
              maxValue={10}
              colorForValue={(value) => fiScoreBarColor(value)}
            />
            <div className="mt-2 flex justify-between text-xs text-slate-400">
              {metrics.history.map((item) => (
                <span key={item.month}>{item.label}</span>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card className={SECTION_CARD}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Кредитная нагрузка</h3>
              <p className="mt-1 text-sm text-slate-500">Сколько дохода сейчас уходит на кредитные обязательства.</p>
            </div>
            <MetricBadge
              tone={getDtiTone(health.dti)}
              label={health.dti < 30 ? 'Зелёная зона' : health.dti < 40 ? 'Погранично' : 'Выше нормы'}
            />
          </div>
          <p className="mt-4 text-3xl font-semibold text-slate-950">{health.dti.toFixed(1)}%</p>
          <MiniBars
            values={metrics.history.map((item) => item.dti)}
            maxValue={50}
            colorForValue={(value) => (value < 30 ? COLORS.green : value < 40 ? COLORS.orange : COLORS.red)}
          />
          <div className="mt-2 flex justify-between text-xs text-slate-400">
            {metrics.history.map((item) => (
              <span key={item.month}>{item.label}</span>
            ))}
          </div>
          <p className="mt-4 text-sm leading-6 text-slate-600">{metrics.dtiText}</p>
        </Card>

        <Card className={SECTION_CARD}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Финансовая независимость</h3>
              <p className="mt-1 text-sm text-slate-500">Сколько расходов уже покрывается пассивным доходом.</p>
            </div>
            <MetricBadge
              tone={getFiTone(health.fi_percent)}
              label={health.fi_zone === 'free' ? 'Свободен' : health.fi_zone === 'on_way' ? 'На пути' : health.fi_zone === 'partial' ? 'Частично' : 'В начале пути'}
            />
          </div>
          <p className="mt-4 text-3xl font-semibold text-slate-950">{health.fi_percent.toFixed(1)}%</p>
          <p className="mt-2 text-sm text-slate-500">пассивный доход покрывает расходы</p>

          <div className="mt-5 border-t border-slate-100 pt-5">
            <div className="h-3 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full"
                style={{ width: `${clamp(health.fi_percent, 0, 100)}%`, backgroundColor: COLORS.blue }}
              />
            </div>
            <div className="mt-2 flex justify-between text-xs text-slate-400">
              <span>0%</span>
              <span>100%</span>
            </div>
          </div>

          <div className="mt-5 border-t border-slate-100 pt-5">
            <p className="text-sm leading-6 text-slate-600">{metrics.independenceText}</p>
          </div>
        </Card>

        <Card className={SECTION_CARD}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Норма сбережений</h3>
              <p className="mt-1 text-sm text-slate-500">Откладываешь от дохода · среднее за 6 мес.</p>
            </div>
            <MetricBadge tone={getSavingsTone(health.avg_savings_rate)} label={health.avg_savings_rate >= 20 ? 'Цель достигнута' : health.avg_savings_rate >= 10 ? 'Нужно усилить' : 'Ниже минимума'} />
          </div>
          <p className="mt-4 text-3xl font-semibold text-slate-950">{health.avg_savings_rate.toFixed(1)}%</p>

          <div className="mt-5 border-t border-slate-100 pt-5">
            <div className="h-4 overflow-hidden rounded-full bg-slate-100">
              <div className="flex h-full w-full overflow-hidden rounded-full">
                <div style={{ width: `${clamp(metrics.avgEssentialRate, 0, 100)}%`, backgroundColor: COLORS.red }} />
                <div style={{ width: `${clamp(metrics.avgSecondaryRate, 0, 100)}%`, backgroundColor: COLORS.orange }} />
                <div style={{ width: `${clamp(metrics.avgSavingsRate, 0, 100)}%`, backgroundColor: COLORS.green }} />
              </div>
            </div>
            <div className="mt-4 space-y-2 text-sm">
              {[
                { label: 'Обязательные', color: COLORS.red, percent: metrics.avgEssentialRate, amount: metrics.avgEssential },
                { label: 'Второстепенные', color: COLORS.orange, percent: metrics.avgSecondaryRate, amount: metrics.avgSecondary },
                { label: 'Сбережения', color: COLORS.green, percent: metrics.avgSavingsRate, amount: metrics.avgSavings },
              ].map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-3 text-slate-600">
                  <div className="flex items-center gap-2">
                    <span className="size-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span>{item.label}</span>
                  </div>
                  <span className="font-medium text-slate-900">
                    {item.percent.toFixed(1)}% · {formatMoney(item.amount)}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5 border-t border-slate-100 pt-5">
            <div className="mb-3 flex flex-wrap items-center gap-3 text-xs font-medium text-slate-500">
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ backgroundColor: COLORS.red }} />Обязательные</span>
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ backgroundColor: COLORS.orange }} />Второстепенные</span>
              <span className="flex items-center gap-1.5"><span className="size-2 rounded-full" style={{ backgroundColor: COLORS.green }} />Сбережения</span>
            </div>
            <h4 className="text-sm font-semibold text-slate-900">Динамика за 6 месяцев</h4>
            <div className="mt-4">
              <SavingsMixChart history={metrics.history} />
            </div>
          </div>

          <div className="mt-5 border-t border-slate-100 pt-5">
            <p className="text-sm font-semibold text-slate-900">Рекомендуемый минимум — 20%</p>
            <p className="mt-2 text-sm leading-6 text-slate-600">{metrics.savingsAdvice}</p>
          </div>
        </Card>

        <Card className={SECTION_CARD}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Финансовая дисциплина</h3>
              <p className="mt-1 text-sm text-slate-500">Насколько стабильно удаётся укладываться в бюджеты.</p>
            </div>
            <MetricBadge
              tone={getDisciplineTone(health.discipline)}
              label={health.discipline === null ? 'Нет бюджета' : health.discipline >= 90 ? 'Отлично' : health.discipline >= 75 ? 'Хорошо' : health.discipline >= 50 ? 'Есть просадки' : 'Слабо'}
            />
          </div>
          <p className="mt-4 text-3xl font-semibold text-slate-950">{health.discipline !== null ? `${health.discipline.toFixed(1)}%` : '—'}</p>
          <p className="mt-2 text-sm text-slate-500">соответствие бюджету</p>

          <div className="mt-5 border-t border-slate-100 pt-5">
            {!metrics.history.length ? (
              <p className="text-sm leading-6 text-slate-500">Недостаточно данных. Продолжай вносить транзакции.</p>
            ) : metrics.allHeatmapMissing ? (
              <p className="text-sm leading-6 text-slate-500">Добавь бюджет по категориям, чтобы отслеживать выполнение плана.</p>
            ) : (
              <>
                <p className="mb-3 text-[11px] font-medium text-slate-400">% выполнения плана по направлениям</p>
                <div className="overflow-x-auto">
                  <table className="w-full border-separate border-spacing-0">
                    <thead>
                      <tr>
                        <th className="w-[130px] px-2 pb-2 text-left text-[11px] font-medium text-slate-400" />
                        {metrics.history.map((month) => (
                          <th key={month.month} className="px-1 pb-2 text-center text-[11px] font-medium text-slate-400">
                            {month.label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.disciplineHeatmapRows.map((row) => (
                        <tr key={row.direction}>
                          <td className="w-[130px] px-2 py-1 text-left text-xs text-slate-500">{row.label}</td>
                          {row.values.map((cell, index) => {
                            const style = getHeatmapCellStyle(row.direction, cell.fulfillment);
                            return (
                              <td key={`${row.direction}-${metrics.history[index]?.month ?? index}`} className="px-0.5 py-1 text-center">
                                <div
                                  className="rounded px-1 py-[3px] text-[11px] font-medium"
                                  style={style}
                                  title={
                                    cell.fulfillment < 0
                                      ? `${row.label}: план не задан`
                                      : `${row.label}: ${Math.round(cell.fulfillment)}% · план ${formatMoney(cell.planned)} · факт ${formatMoney(cell.actual)}`
                                  }
                                >
                                  {cell.fulfillment < 0 ? '—' : `${Math.round(cell.fulfillment)}%`}
                                </div>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          <div className="mt-5 border-t border-slate-100 pt-5">
            <p className="text-sm leading-6 text-slate-600">{metrics.disciplineText}</p>
          </div>

          {metrics.chronicUnderperformers.length > 0 ? (
            <div className="mt-5 border-t border-slate-100 pt-5">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-slate-400">Систематические нарушения</p>
              <div>
                {metrics.chronicUnderperformers.slice(0, 3).map((item) => {
                  const trendIcon = item.trend === 'worsening'
                    ? <TrendingDown className="size-[14px]" color="#A32D2D" />
                    : item.trend === 'improving'
                      ? <TrendingUp className="size-[14px]" color="#3B6D11" />
                      : <Minus className="size-[14px]" color="#888780" />;
                  const pillClass = item.months_count >= 3
                    ? 'bg-rose-50 text-rose-700'
                    : 'bg-amber-50 text-amber-700';
                  const avgColor = item.direction.startsWith('income')
                    ? (item.avg_fulfillment < 70 ? '#A32D2D' : '#854F0B')
                    : (item.avg_fulfillment > 150 ? '#A32D2D' : '#854F0B');

                  return (
                    <div key={`${item.direction}-${item.category_id}`} className="border-b border-slate-200/70 py-[7px] last:border-b-0">
                      <div className="flex items-center gap-2">
                        {trendIcon}
                        <span className="flex-1 text-[13px] text-slate-900">{item.category_name}</span>
                        <span className={cn('rounded-full px-[7px] py-[2px] text-[11px] font-medium', pillClass)}>
                          {item.months_count} мес. подряд
                        </span>
                        <span className="min-w-9 text-right text-xs font-medium" style={{ color: avgColor }}>
                          {Math.round(item.avg_fulfillment)}%
                        </span>
                      </div>
                      <p className="mt-0.5 pl-[22px] text-[11px] text-slate-400">
                        {item.direction_label} · план {formatRublesCompact(item.last_planned)} → факт {formatRublesCompact(item.last_actual)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {metrics.unplannedCategories.length > 0 ? (
            <div className="mt-5 border-t border-slate-100 pt-5">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.06em] text-slate-400">Регулярные траты без плана</p>
              <p className="mb-2.5 text-xs text-slate-500">Эти категории регулярно съедают деньги, но не включены в бюджет</p>
              <div>
                {metrics.unplannedCategories.map((item) => {
                  const isEssential = item.direction === 'expense_essential';
                  return (
                    <div key={`${item.direction}-${item.category_id}`} className="border-b border-slate-200/70 py-[7px] last:border-b-0">
                      <div className="flex items-center gap-2">
                        <span className="size-2 rounded-full" style={{ backgroundColor: isEssential ? COLORS.red : COLORS.orange }} />
                        <span className="flex-1 text-[13px] text-slate-900">{item.category_name}</span>
                        <span
                          className="rounded-full px-1.5 py-[1px] text-[10px] font-medium"
                          style={{
                            backgroundColor: isEssential ? '#FCEBEB' : '#FAEEDA',
                            color: isEssential ? '#A32D2D' : '#854F0B',
                          }}
                        >
                          {item.direction_label}
                        </span>
                        <span className="text-xs font-medium text-slate-900">
                          {Math.round(item.avg_monthly_amount).toLocaleString('ru-RU')} ₽/мес
                        </span>
                      </div>
                      <p className="mt-0.5 pl-4 text-[11px] text-slate-400">
                        встречается в {item.months_with_spending} из {health.months_calculated} мес.
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {!metrics.chronicUnderperformers.length && !metrics.unplannedCategories.length ? (
            <div className="mt-5 border-t border-slate-100 pt-5">
              <div className="flex items-center gap-2 text-[13px] text-slate-500">
                <CheckCircle2 className="size-4 text-emerald-600" />
                <span>Всё под контролем — нарушений нет</span>
              </div>
            </div>
          ) : null}
        </Card>
      </section>

      <section>
        <Card className={SECTION_CARD}>
          <div className="flex items-start gap-3">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700">
              <HeartPulse className="size-5" />
            </div>
            <div>
              <h3 className="text-lg font-semibold text-slate-950">Что делать прямо сейчас</h3>
              <p className="mt-1 text-sm text-slate-500">Три ближайших шага по приоритету, чтобы двигаться в правильную сторону без перегруза.</p>
            </div>
          </div>

          <div className="mt-6 space-y-4">
            {metrics.actionSteps.map((step, index) => (
              <div key={step.key} className="flex items-start gap-4 rounded-2xl bg-slate-50/80 p-4">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-sm font-semibold text-emerald-700">
                  {index + 1}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium leading-6 text-slate-900">{step.title}</p>
                  <Link href={step.href} className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-sky-600 transition hover:text-sky-700">
                    {step.lesson} <ArrowRight className="size-4" />
                  </Link>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </PageShell>
  );
}
