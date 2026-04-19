'use client';

import { useMemo, useState } from 'react';
import type { MetricsSummary } from '@/lib/api/metrics';
import type { Transaction } from '@/types/transaction';
import {
  computeFlowBreakdown,
  computeFlowForPeriod,
  getTransactionYears,
  getTransactionMonths,
} from './dashboard-data';

// Ref: financeapp-vault/01-Metrics/Поток.md
// Ref: financeapp-vault/15-Hypotheses/Гипотеза — UX виджета ДДС.md
// Port of trilayer-flow-widget.html (light-theme adaptation).

type Tab = 'basic' | 'free' | 'full';

type Props = {
  summary: MetricsSummary | null;
  transactions: Transaction[];
  ccAccountIds?: Set<number>;
  isLoading?: boolean;
};

const MONTH_NAMES = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];

type Segment = {
  color: string;
  value: number;
  label: string;
};

// SVG constants — all tabs render as "speedometer" (unfinished arc at bottom).
const OUTER_R = 80;
const INNER_R = 58;
const OUTER_SW = 14;
const INNER_SW = 12;
const OUTER_CIRC = 2 * Math.PI * OUTER_R;
const INNER_CIRC = 2 * Math.PI * INNER_R;
// Visual arc occupies 62% of circumference (bottom gap ≈ 137°) — pronounced "speedometer" cut.
const MAX_FRACTION = 0.62;
const OUTER_MAX = OUTER_CIRC * MAX_FRACTION;
const INNER_MAX = INNER_CIRC * MAX_FRACTION;

const COLORS = {
  cyan: '#06b6d4',
  rose: '#f43f5e',
  slate: '#94a3b8',
  violet: '#8b5cf6',
  amber: '#fbbf24',
  emerald: '#10b981',
  blue: '#60a5fa',
  track: '#e2e8f0',
};

function formatRub(value: number): string {
  const sign = value < 0 ? '−' : value > 0 ? '+' : '';
  const abs = Math.abs(Math.round(value));
  const formatted = new Intl.NumberFormat('ru-RU').format(abs);
  return `${sign}${formatted} ₽`;
}

function formatCenter(value: number): string {
  const sign = value < 0 ? '−' : value > 0 ? '+' : '';
  const abs = Math.abs(Math.round(value));
  return `${sign}${new Intl.NumberFormat('ru-RU').format(abs)}`;
}

type DrawSegment = {
  stroke: string;
  arcLen: number;
  offset: number;
};

function buildArcs(segments: Segment[], maxVal: number, maxArc: number): DrawSegment[] {
  if (maxVal <= 0) return [];
  // maxArc already includes the speedometer cut — segments fill it proportionally.
  // The ring whose sum equals maxVal fills the entire arc; the other ring fills proportionally less.
  let offset = 0;
  const arcs: DrawSegment[] = [];
  for (const seg of segments) {
    if (seg.value <= 0) continue;
    const len = (seg.value / maxVal) * maxArc;
    arcs.push({ stroke: seg.color, arcLen: len, offset });
    offset += len;
  }
  return arcs;
}

// Visible gap between adjacent segments.
const SEG_GAP = 4;

function renderArcs(arcs: DrawSegment[], r: number, sw: number, circ: number) {
  // butt caps + small gaps between segments → clean "speedometer" look.
  return arcs.map((a, i) => {
    const isLast = i === arcs.length - 1;
    const isFirst = i === 0;
    // Trim each side that touches another segment by SEG_GAP/2.
    const leftTrim = isFirst ? 0 : SEG_GAP / 2;
    const rightTrim = isLast ? 0 : SEG_GAP / 2;
    const trimmed = Math.max(a.arcLen - leftTrim - rightTrim, 0);
    const off = a.offset + leftTrim;
    return (
      <circle
        key={i}
        cx={120}
        cy={120}
        r={r}
        fill="none"
        stroke={a.stroke}
        strokeWidth={sw}
        strokeDasharray={`${trimmed} ${circ}`}
        strokeDashoffset={-off}
        strokeLinecap="butt"
        style={{ transition: 'stroke-dasharray 400ms ease, stroke-dashoffset 400ms ease' }}
      />
    );
  });
}

type HintTone = 'healthy' | 'tight' | 'deficit' | 'neutral';

const HINT_CLASSES: Record<HintTone, string> = {
  healthy: 'border-emerald-400 bg-emerald-50 text-emerald-800',
  tight: 'border-amber-400 bg-amber-50 text-amber-800',
  deficit: 'border-rose-400 bg-rose-50 text-rose-800',
  neutral: 'border-slate-300 bg-slate-50 text-slate-700',
};


function HintToggle({ tone, children }: { tone: HintTone; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-600"
      >
        <span>Узнать, что это значит</span>
        <svg
          className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M2 4l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className={`mt-2 rounded-xl border-l-4 px-3 py-2 text-sm ${HINT_CLASSES[tone]}`}>
          {children}
        </div>
      )}
    </div>
  );
}

function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="group relative ml-1 inline-flex items-center">
      <span className="cursor-help text-slate-300 transition-colors hover:text-slate-500">
        <svg className="h-3.5 w-3.5" viewBox="0 0 16 16" fill="currentColor">
          <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 3a.75.75 0 1 1 0 1.5A.75.75 0 0 1 8 4zm-.75 3h1.5v5h-1.5V7z" />
        </svg>
      </span>
      <span className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-52 -translate-x-1/2 rounded-lg bg-slate-800 px-2.5 py-2 text-xs leading-relaxed text-white opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
        {text}
        <span className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-slate-800" />
      </span>
    </span>
  );
}

function RowItem({
  color,
  label,
  amount,
  tooltip,
  isTotal,
}: {
  color?: string;
  label: string;
  amount: number;
  tooltip?: string;
  isTotal?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-between py-2 text-sm ${
        isTotal
          ? 'mt-1 border-t border-slate-200 pt-3 font-semibold text-slate-900'
          : 'border-b border-slate-100 last:border-0'
      }`}
    >
      <span className={`flex items-center gap-2 ${isTotal ? 'text-slate-900' : 'text-slate-600'}`}>
        {color ? (
          <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />
        ) : (
          <span className="inline-block h-2 w-2 shrink-0" />
        )}
        <span className="flex items-center">
          {label}
          {tooltip ? <InfoTooltip text={tooltip} /> : null}
        </span>
      </span>
      <span className={`font-medium tabular-nums ${amount < 0 ? 'text-rose-600' : 'text-slate-900'}`}>
        {formatRub(amount)}
      </span>
    </div>
  );
}

function InvestmentBar({
  value,
  total,
  label,
  hint,
  forceFull = false,
}: {
  value: number;
  total: number;
  label: string;
  hint: string;
  forceFull?: boolean;
}) {
  const pct = forceFull ? 100 : Math.max(0, Math.min(100, total > 0 ? (value / total) * 100 : 0));
  return (
    <div className="mt-3 rounded-xl bg-violet-50 px-3 py-2">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="font-semibold tabular-nums text-violet-700">{formatRub(value)}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-violet-100">
        <div className="h-full rounded-full bg-violet-500" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  );
}

export function FlowWidget({ summary, transactions, ccAccountIds, isLoading }: Props) {
  const [tab, setTab] = useState<Tab>('basic');

  // ── Period state ───────────────────────────────────────────────
  const now = new Date();
  const [selectedYear, setSelectedYear] = useState(now.getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth());

  const isCurrentMonth =
    selectedYear === now.getFullYear() && selectedMonth === now.getMonth();

  const years = useMemo(() => {
    const ys = getTransactionYears(transactions);
    const cy = now.getFullYear();
    if (!ys.includes(cy)) ys.unshift(cy);
    return ys;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transactions]);

  const availableMonths = useMemo(() => {
    const months = getTransactionMonths(transactions, selectedYear);
    const cy = now.getFullYear();
    const cm = now.getMonth();
    if (selectedYear === cy && !months.includes(cm)) months.push(cm);
    months.sort((a, b) => a - b);
    return months.length > 0 ? months : [now.getMonth()];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transactions, selectedYear]);

  // ── Breakdown for selected period ──────────────────────────────
  const breakdown = useMemo(
    () => computeFlowBreakdown(transactions, { year: selectedYear, month: selectedMonth }),
    [transactions, selectedYear, selectedMonth],
  );

  // ── Core metrics: API for current month, client-side for historical ──
  const periodMetrics = useMemo(
    () => computeFlowForPeriod(transactions, selectedYear, selectedMonth, ccAccountIds),
    [transactions, selectedYear, selectedMonth, ccAccountIds],
  );

  const data = useMemo(() => {
    if (isCurrentMonth && summary) {
      const { basic_flow, free_capital, full_flow, cc_debt_compensator, credit_body_payments, lifestyle_indicator, zone } = summary.flow;
      return {
        basicFlow: Number(basic_flow),
        freeCapital: Number(free_capital),
        fullFlow: Number(full_flow),
        ccCompensator: Number(cc_debt_compensator),
        creditBody: Number(credit_body_payments),
        // ccRepayment / earlyRepayment are not exposed by API — always take client-side
        ccRepayment: periodMetrics.ccRepayment,
        earlyRepayment: periodMetrics.earlyRepayment,
        lifestyle: lifestyle_indicator,
        zone: zone as string,
      };
    }
    // Historical month: compute from transactions
    return {
      basicFlow: periodMetrics.basicFlow,
      freeCapital: periodMetrics.freeCapital,
      fullFlow: periodMetrics.fullFlow,
      ccCompensator: periodMetrics.ccCompensator,
      creditBody: periodMetrics.creditBody,
      ccRepayment: periodMetrics.ccRepayment,
      earlyRepayment: periodMetrics.earlyRepayment,
      lifestyle: periodMetrics.lifestyleCurrent,
      zone: 'neutral',
    };
  }, [isCurrentMonth, summary, periodMetrics]);

  if (isLoading || !data) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
        <div className="mb-4 flex items-center justify-between">
          <div className="h-5 w-40 animate-pulse rounded bg-slate-100" />
          <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
        </div>
        <div className="flex gap-4">
          <div className="h-[240px] w-[240px] shrink-0 animate-pulse rounded-full bg-slate-100" />
          <div className="flex-1 space-y-3">
            <div className="h-4 animate-pulse rounded bg-slate-100" />
            <div className="h-4 animate-pulse rounded bg-slate-100" />
            <div className="h-4 animate-pulse rounded bg-slate-100" />
          </div>
        </div>
      </div>
    );
  }

  // Segments per tab
  let outerSegs: Segment[] = [];
  let innerSegs: Segment[] = [];
  let centerAmount = 0;
  let centerLabel = '';

  if (tab === 'basic') {
    outerSegs = [{ color: COLORS.cyan, value: breakdown.regularIncome, label: 'Регулярные доходы' }];
    innerSegs = [{ color: COLORS.rose, value: breakdown.regularExpenses, label: 'Регулярные расходы' }];
    centerAmount = data.basicFlow;
    centerLabel = 'БАЗОВЫЙ';
  } else if (tab === 'free') {
    outerSegs = [{ color: COLORS.cyan, value: breakdown.regularIncome, label: 'Регулярные доходы' }];
    innerSegs = [
      { color: COLORS.rose, value: breakdown.regularExpenses, label: 'Регулярные расходы' },
      { color: COLORS.slate, value: data.creditBody, label: 'Тело кредитов' },
    ];
    centerAmount = data.freeCapital;
    centerLabel = 'СВОБОДНЫЙ';
  } else {
    // Full flow decomposition:
    // Outer = physical + accounting inflow: income + credit disbursement + CC purchases compensator
    // Inner = outflow: expenses (incl. CC) + credit body + investments
    outerSegs = [
      { color: COLORS.cyan, value: breakdown.allIncome, label: 'Доходы' },
    ];
    if (breakdown.creditDisbursement > 0) {
      outerSegs.push({ color: COLORS.emerald, value: breakdown.creditDisbursement, label: 'Кредитные поступления' });
    }
    if (data.ccCompensator > 0) {
      outerSegs.push({ color: COLORS.amber, value: data.ccCompensator, label: 'Покупки на КК' });
    }
    innerSegs = [
      { color: COLORS.rose, value: breakdown.allExpenses, label: 'Расходы' },
      { color: COLORS.slate, value: data.creditBody + data.ccRepayment + data.earlyRepayment, label: 'Кредитные платежи' },
    ];
    if (breakdown.investmentBuy > 0) {
      innerSegs.push({ color: COLORS.violet, value: breakdown.investmentBuy, label: 'Инвестиции' });
    }
    centerAmount = data.fullFlow;
    centerLabel = 'Δ КЭША';
  }

  const sumOuter = outerSegs.reduce((s, x) => s + x.value, 0);
  const sumInner = innerSegs.reduce((s, x) => s + x.value, 0);
  const maxVal = Math.max(sumOuter, sumInner, 1);
  const outerArcs = buildArcs(outerSegs, maxVal, OUTER_MAX);
  const innerArcs = buildArcs(innerSegs, maxVal, INNER_MAX);

  // Current month percentage: basicFlow / regularIncome × 100
  const currentPct =
    breakdown.regularIncome > 0
      ? Math.round((data.basicFlow / breakdown.regularIncome) * 100 * 10) / 10
      : null;

  // Hint
  let hintTone: 'healthy' | 'tight' | 'deficit' | 'neutral' = 'neutral';
  let hintText = '';
  if (tab === 'basic') {
    const avgSuffix =
      data.lifestyle !== null && currentPct !== null
        ? ` В среднем за 12 мес: ${data.lifestyle}%.`
        : '';
    if (data.basicFlow < 0) {
      hintTone = 'deficit';
      hintText = `Регулярные расходы превышают доход на ${formatRub(Math.abs(data.basicFlow))}/мес. Сократи второстепенные.${avgSuffix}`;
    } else if (currentPct === null) {
      hintTone = 'neutral';
      hintText = 'Нет данных о регулярных доходах в этом месяце.';
    } else if (currentPct < 20) {
      hintTone = 'tight';
      hintText = `После трат остаётся ${currentPct}% дохода. Одна непредвиденная трата выведет в минус.${avgSuffix}`;
    } else {
      hintTone = 'healthy';
      hintText = `${currentPct}% дохода остаётся после регулярных трат. Образ жизни устойчив.${avgSuffix}`;
    }
  } else if (tab === 'free') {
    if (data.freeCapital > 0) {
      hintTone = 'healthy';
      hintText = `${formatRub(data.freeCapital)} ежемесячно освобождается. Направь на цели, досрочное погашение или инвестиции.`;
    } else {
      hintTone = 'deficit';
      hintText = 'Обязательные платежи забирают больше, чем освобождается. Фокус — снижать DTI.';
    }
  } else {
    if (data.fullFlow < 0) {
      hintTone = 'deficit';
      hintText = `На счетах ${formatRub(data.fullFlow)} за месяц. Крупная покупка, досрочное погашение или превышение обязательств.`;
    } else if (data.ccCompensator > 0) {
      hintTone = 'neutral';
      const realGrowth = data.fullFlow - data.ccCompensator;
      hintText = `На счетах ${formatRub(data.fullFlow)}. Из них ${formatRub(data.ccCompensator)} — покупки в кредит (погасятся в следующем месяце). Реальный прирост своих: ${formatRub(realGrowth)}.`;
    } else {
      hintTone = 'neutral';
      hintText = `На счетах ${formatRub(data.fullFlow)} за месяц.`;
    }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'basic', label: 'Базовый' },
    { key: 'free', label: 'Свободный' },
    { key: 'full', label: 'Полный' },
  ];

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-slate-900">Денежный поток</h3>
        <div className="flex items-center gap-2">
          <select
            value={selectedYear}
            onChange={(e) => setSelectedYear(Number(e.target.value))}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            {years.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
          <select
            value={selectedMonth}
            onChange={(e) => setSelectedMonth(Number(e.target.value))}
            className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            {availableMonths.map((idx) => (
              <option key={idx} value={idx}>{MONTH_NAMES[idx]}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="mb-4 flex gap-1 rounded-xl bg-slate-100 p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`flex-1 rounded-lg px-3 py-1.5 text-sm font-medium transition ${
              tab === t.key
                ? 'bg-white text-slate-900 shadow-sm'
                : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mb-5 flex justify-center">
        <svg viewBox="0 0 240 240" width={240} height={240} className="shrink-0">
          <g transform="rotate(135 120 120)">
            <circle cx={120} cy={120} r={OUTER_R} fill="none" stroke={COLORS.track} strokeWidth={OUTER_SW}
              strokeDasharray={`${OUTER_MAX} ${OUTER_CIRC}`} strokeLinecap="butt" />
            <circle cx={120} cy={120} r={INNER_R} fill="none" stroke={COLORS.track} strokeWidth={INNER_SW}
              strokeDasharray={`${INNER_MAX} ${INNER_CIRC}`} strokeLinecap="butt" />
            {renderArcs(outerArcs, OUTER_R, OUTER_SW, OUTER_CIRC)}
            {renderArcs(innerArcs, INNER_R, INNER_SW, INNER_CIRC)}
          </g>
          <text
            x={120}
            y={117}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-slate-900"
            style={{ fontSize: 22, fontWeight: 700 }}
          >
            {formatCenter(centerAmount)}
          </text>
          <text
            x={120}
            y={140}
            textAnchor="middle"
            dominantBaseline="middle"
            className="fill-slate-400"
            style={{ fontSize: 10, letterSpacing: 2 }}
          >
            {centerLabel}
          </text>
        </svg>
      </div>

      <div>
        <div>
          {tab === 'basic' ? (
            <>
              <RowItem color={COLORS.cyan} label="Регулярные доходы" amount={breakdown.regularIncome} />
              <RowItem color={COLORS.rose} label="Регулярные расходы" amount={-breakdown.regularExpenses} />
            </>
          ) : tab === 'free' ? (
            <>
              <RowItem color={COLORS.cyan} label="Регулярные доходы" amount={breakdown.regularIncome} />
              <RowItem color={COLORS.rose} label="Регулярные расходы" amount={-breakdown.regularExpenses} />
              <RowItem
                color={COLORS.slate}
                label="Кредитные платежи"
                tooltip="Только тело обязательных платежей по кредитам (без процентов — они уже в регулярных расходах)"
                amount={-data.creditBody}
              />
              {data.freeCapital > 0 && breakdown.investmentBuy > 0 ? (
                <InvestmentBar
                  value={breakdown.investmentBuy}
                  total={data.freeCapital}
                  label="Инвестиции"
                  hint={`Из ${formatRub(data.freeCapital)} свободных → ${formatRub(breakdown.investmentBuy)} вложено`}
                />
              ) : null}
            </>
          ) : (
            <>
              <RowItem
                color={COLORS.cyan}
                label="Доходы"
                tooltip="Все поступления: активные и пассивные, регулярные и нерегулярные"
                amount={breakdown.allIncome}
              />
              {breakdown.creditDisbursement > 0 ? (
                <RowItem
                  color={COLORS.emerald}
                  label="Кредитные поступления"
                  tooltip="Выдача кредита на дебетовый счёт — физическое поступление кэша (но это долг, не доход)"
                  amount={breakdown.creditDisbursement}
                />
              ) : null}
              <RowItem
                color={COLORS.rose}
                label="Расходы"
                tooltip="Все расходы за месяц, включая покупки с кредитной карты"
                amount={-breakdown.allExpenses}
              />
              <RowItem
                color={COLORS.slate}
                label="Кредитные платежи"
                tooltip="Тело обязательных платежей по кредитам + погашение кредитных карт и карт рассрочки с дебетовых счетов + досрочные погашения (проценты уже в расходах)"
                amount={-(data.creditBody + data.ccRepayment + data.earlyRepayment)}
              />
              {breakdown.investmentBuy > 0 ? (
                <RowItem color={COLORS.violet} label="Инвестиции" amount={-breakdown.investmentBuy} />
              ) : null}
              {data.ccCompensator > 0 ? (
                <RowItem
                  color={COLORS.amber}
                  label="Покупки на КК"
                  tooltip="Покупки на КК не уменьшают кэш на ликвидных счетах — вырастает долг по кредитке. Эта строка компенсирует разрыв, чтобы декомпозиция сошлась."
                  amount={data.ccCompensator}
                />
              ) : null}
            </>
          )}
        </div>
      </div>

      <HintToggle tone={hintTone}>{hintText}</HintToggle>
    </div>
  );
}

