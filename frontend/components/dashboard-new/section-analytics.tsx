'use client';

import { useState, useMemo, useEffect } from 'react';
import type {
  FlowType,
  TrendData,
  TrendPoint,
  TopExpenseItem,
  IncomeStructureData,
} from '@/components/dashboard-new/dashboard-data';
import {
  formatRub,
  TAG_CLASSES,
  computeTopExpenses,
  computeExpenseTotals,
  getTransactionYears,
  getTransactionMonths,
} from '@/components/dashboard-new/dashboard-data';
import { ExpandableCard } from '@/components/dashboard-new/expandable-card';
import type { Transaction } from '@/types/transaction';
import type { Category } from '@/types/category';

type Props = {
  trend: TrendData | null;
  topExpenses: TopExpenseItem[];
  totalExpenses: number;
  incomeStructure: IncomeStructureData | null;
  avgDailyExpense: number;
  installmentCards: Array<{ name: string; monthlyPayment: number; remaining: number | null; totalAmount: number }>;
  transactions: Transaction[];
  categories: Category[];
  // Trend controls
  trendYears: number[];
  trendYear: number;
  trendMonth: number;
  flowType: FlowType;
  availableMonths: number[];
  onTrendYearChange: (year: number) => void;
  onTrendMonthChange: (month: number) => void;
  onFlowTypeChange: (type: FlowType) => void;
};

/* ── Helpers ─────────────────────────────────────────────────── */

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center py-8 text-sm text-slate-400">
      {text}
    </div>
  );
}

function anomalyDot(status: 'spike' | 'drift' | 'normal') {
  if (status === 'spike') return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#E24B4A]" />;
  if (status === 'drift') return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#EF9F27]" />;
  return <span className="w-1.5 shrink-0" />;
}

const MONTH_NAMES = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
];

const MONTH_SHORT = [
  'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
  'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек',
];

/* ── Trend Donut (SVG with transitions) ────────────────────── */

function TrendDonut({ trend }: { trend: TrendData }) {
  const s = trend.selected;
  const total = s.income + s.expense + s.creditPayments;
  const incomePct = total > 0 ? s.income / total : 1 / 3;
  const expensePct = total > 0 ? s.expense / total : 1 / 3;
  const creditPct = total > 0 ? s.creditPayments / total : 1 / 3;

  const R = 72;
  const C = 2 * Math.PI * R;

  const segments = [
    { color: '#06b6d4', pct: incomePct },
    { color: '#f43f5e', pct: expensePct },
    { color: '#94a3b8', pct: creditPct },
  ];

  let cumulative = 0;
  const arcs = segments.map((seg) => {
    const len = seg.pct * C;
    const dashOffset = C - cumulative;
    cumulative += len;
    return { ...seg, len, dashOffset };
  });

  return (
    <div className="flex items-center gap-6 mt-4">
      {/* SVG Donut */}
      <div className="relative shrink-0" style={{ width: 180, height: 180 }}>
        <svg width="180" height="180" viewBox="0 0 180 180">
          <g transform="rotate(-90 90 90)">
            {arcs.map((arc, i) => (
              <circle
                key={i}
                cx="90"
                cy="90"
                r={R}
                fill="none"
                stroke={arc.color}
                strokeWidth="18"
                strokeLinecap="butt"
                strokeDasharray={`${arc.len} ${C - arc.len}`}
                strokeDashoffset={arc.dashOffset}
                style={{
                  transition:
                    'stroke-dasharray 0.6s cubic-bezier(0.4, 0, 0.2, 1), stroke-dashoffset 0.6s cubic-bezier(0.4, 0, 0.2, 1)',
                }}
              />
            ))}
          </g>
        </svg>
        <div className="absolute inset-[38px] rounded-full bg-white flex flex-col items-center justify-center">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400 leading-tight">
            {s.balance >= 0 ? 'Остаток' : 'Дефицит'}
          </span>
          <span className={`text-lg font-extrabold leading-tight ${s.balance >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
            {formatRub(s.balance)}
          </span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 shrink-0 rounded-full bg-cyan-500" />
          <div>
            <p className="text-xs text-slate-500">Доходы</p>
            <p className="text-sm font-bold text-cyan-600">{formatRub(s.income)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 shrink-0 rounded-full bg-rose-500" />
          <div>
            <p className="text-xs text-slate-500">Расходы</p>
            <p className="text-sm font-bold text-rose-600">{formatRub(s.expense)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-3 w-3 shrink-0 rounded-full bg-slate-400" />
          <div>
            <p className="text-xs text-slate-500">Кредиты</p>
            <p className="text-sm font-bold text-slate-500">{formatRub(s.creditPayments)}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Bar Tooltip ───────────────────────────────────────────── */

function BarTooltip({
  point,
  kind,
  x,
  y,
}: {
  point: TrendPoint;
  kind: 'income' | 'expense' | 'balance';
  x: number;
  y: number;
}) {
  const bd = point.incomeBreakdown;
  const ed = point.expenseBreakdown;

  return (
    <div
      className="absolute z-50 pointer-events-none rounded-xl bg-slate-800 text-white px-3.5 py-2.5 text-xs shadow-lg whitespace-nowrap"
      style={{
        left: x,
        top: y,
        transform: 'translate(-50%, -100%)',
        marginTop: -8,
      }}
    >
      {kind === 'income' && (
        <>
          <p className="font-semibold text-cyan-300 mb-1.5">Доходы: {formatRub(point.income)}</p>
          {bd.activeRegular > 0 && <p>Активный регулярный: {formatRub(bd.activeRegular)}</p>}
          {bd.activeIrregular > 0 && <p>Активный нерегулярный: {formatRub(bd.activeIrregular)}</p>}
          {bd.passiveRegular > 0 && <p>Пассивный регулярный: {formatRub(bd.passiveRegular)}</p>}
          {bd.passiveIrregular > 0 && <p>Пассивный нерегулярный: {formatRub(bd.passiveIrregular)}</p>}
        </>
      )}
      {kind === 'expense' && (
        <>
          <p className="font-semibold text-rose-300 mb-1.5">Расходы: {formatRub(point.expense)}</p>
          {ed.essentialRegular > 0 && <p>Обязательные регулярные: {formatRub(ed.essentialRegular)}</p>}
          {ed.essentialIrregular > 0 && <p>Обязательные нерегулярные: {formatRub(ed.essentialIrregular)}</p>}
          {ed.secondaryRegular > 0 && <p>Второстепенные регулярные: {formatRub(ed.secondaryRegular)}</p>}
          {ed.secondaryIrregular > 0 && <p>Второстепенные нерегулярные: {formatRub(ed.secondaryIrregular)}</p>}
          {point.creditPayments > 0 && (
            <p className="mt-1 pt-1 border-t border-slate-600">Кредитные платежи: {formatRub(point.creditPayments)}</p>
          )}
        </>
      )}
      {kind === 'balance' && (
        <p className={`font-semibold ${point.balance >= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
          {point.balance >= 0 ? 'Остаток' : 'Дефицит'}: {formatRub(point.balance)}
        </p>
      )}
    </div>
  );
}

/* ── Trend Chart (negative values + transitions + tooltips) ── */

function TrendChart({ trend }: { trend: TrendData }) {
  const [hover, setHover] = useState<{
    point: TrendPoint;
    kind: 'income' | 'expense' | 'balance';
    x: number;
    y: number;
  } | null>(null);

  const points = trend.points;

  const maxPos = Math.max(
    ...points.map((p) => Math.max(p.income, p.expense, Math.max(0, p.balance))),
    1,
  );
  const minNeg = Math.min(...points.map((p) => Math.min(0, p.balance)), 0);
  const absNeg = Math.abs(minNeg);
  const totalRange = maxPos + absNeg || 1;
  const hasNegative = minNeg < 0;

  const posPct = (maxPos / totalRange) * 100;
  const negPct = hasNegative ? (absNeg / totalRange) * 100 : 0;

  const handleBarEnter = (
    e: React.MouseEvent,
    point: TrendPoint,
    kind: 'income' | 'expense' | 'balance',
  ) => {
    const rect = (e.currentTarget.closest('[data-chart-root]') as HTMLElement)?.getBoundingClientRect();
    const barRect = e.currentTarget.getBoundingClientRect();
    if (!rect) return;
    setHover({
      point,
      kind,
      x: barRect.left + barRect.width / 2 - rect.left,
      y: barRect.top - rect.top,
    });
  };

  const handleBarLeave = () => setHover(null);

  return (
    <div className="mt-3 relative" data-chart-root>
      {/* Tooltip — outside height-constrained area so it doesn't clip */}
      {hover && (
        <BarTooltip point={hover.point} kind={hover.kind} x={hover.x} y={hover.y} />
      )}
      <div className="relative" style={{ height: 200 }}>

        {/* Zero line */}
        {hasNegative && (
          <div
            className="absolute left-2 right-2 h-px bg-slate-400 z-10"
            style={{ top: `${posPct}%` }}
          />
        )}
        {/* Negative zone background */}
        {hasNegative && (
          <div
            className="absolute left-2 right-2 bg-rose-50/60 rounded-b-lg pointer-events-none"
            style={{ top: `${posPct}%`, height: `${negPct}%` }}
          />
        )}

        {/* Bar columns */}
        <div className="flex gap-1.5 h-full px-2">
          {points.map((p) => (
            <div key={p.key} className="flex-1 flex flex-col min-w-0">
              {/* Positive zone */}
              <div
                className="flex items-end gap-0.5 shrink-0"
                style={{ height: `${posPct}%` }}
              >
                <div
                  className="flex-1 rounded-t-md min-w-0 bg-cyan-200 transition-all duration-500 ease-out cursor-pointer hover:bg-cyan-300"
                  style={{ height: `${(p.income / maxPos) * 100}%` }}
                  onMouseEnter={(e) => handleBarEnter(e, p, 'income')}
                  onMouseLeave={handleBarLeave}
                />
                <div
                  className="flex-1 rounded-t-md min-w-0 bg-rose-200 transition-all duration-500 ease-out cursor-pointer hover:bg-rose-300"
                  style={{ height: `${(p.expense / maxPos) * 100}%` }}
                  onMouseEnter={(e) => handleBarEnter(e, p, 'expense')}
                  onMouseLeave={handleBarLeave}
                />
                <div
                  className="flex-1 rounded-t-md min-w-0 bg-emerald-200 transition-all duration-500 ease-out cursor-pointer hover:bg-emerald-300"
                  style={{
                    height: `${(Math.max(0, p.balance) / maxPos) * 100}%`,
                  }}
                  onMouseEnter={(e) => handleBarEnter(e, p, 'balance')}
                  onMouseLeave={handleBarLeave}
                />
              </div>

              {/* Negative zone */}
              {hasNegative && (
                <div
                  className="flex items-start gap-0.5 shrink-0"
                  style={{ height: `${negPct}%` }}
                >
                  <div className="flex-1 min-w-0" />
                  <div className="flex-1 min-w-0" />
                  <div
                    className="flex-1 rounded-b-md min-w-0 bg-red-500 transition-all duration-500 ease-out cursor-pointer hover:bg-red-600"
                    style={{
                      height: `${
                        p.balance < 0 && absNeg > 0
                          ? (Math.abs(p.balance) / absNeg) * 100
                          : 0
                      }%`,
                    }}
                    onMouseEnter={(e) => handleBarEnter(e, p, 'balance')}
                    onMouseLeave={handleBarLeave}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Month labels */}
      <div className="flex justify-between text-[10px] text-slate-400 mt-2 px-2">
        {points.map((p) => (
          <span key={p.key} className="flex-1 text-center">
            {p.label}
          </span>
        ))}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 mt-2 px-2 text-[10px] text-slate-400">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-cyan-200" />
          Доходы
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-rose-200" />
          Расходы
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-emerald-200" />
          Остаток
        </span>
        {hasNegative && (
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-sm bg-red-500" />
            Дефицит
          </span>
        )}
      </div>
    </div>
  );
}

/* ── Top Expense Categories (Collapsed — enhanced) ──────────── */

function TopExpenseCategoriesCollapsed({
  items,
  totalExpenses,
}: {
  items: TopExpenseItem[];
  totalExpenses: number;
}) {
  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-800">Топ категорий расходов</p>
          <p className="text-xs text-slate-400 mt-0.5">за текущий месяц</p>
        </div>
        <div className="text-right">
          <p className="text-base font-bold text-slate-900">{formatRub(totalExpenses)}</p>
        </div>
      </div>

      {/* Category list with bars */}
      <div className="mt-3 space-y-2.5">
        {items.map((item) => {
          const pct = totalExpenses > 0 ? (item.amount / totalExpenses) * 100 : 0;
          const barColor =
            item.status === 'spike'
              ? 'bg-[#E24B4A]'
              : item.status === 'drift'
                ? 'bg-[#EF9F27]'
                : 'bg-[#378ADD]';
          return (
            <div key={item.name}>
              <div className="flex items-center gap-2 mb-1">
                {anomalyDot(item.status)}
                <span className="text-sm text-slate-800 flex-1 truncate">{item.name}</span>
                {item.status === 'spike' && (
                  <span className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0 bg-red-50 text-red-600">
                    ↑ всплеск
                  </span>
                )}
                {item.status === 'drift' && (
                  <span className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0 bg-amber-50 text-amber-600">
                    ↗ дрифт
                  </span>
                )}
                {item.isRegular ? (
                  <span className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0 bg-emerald-50 text-emerald-600">
                    рег.
                  </span>
                ) : (
                  <span className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0 bg-amber-50 text-amber-600">
                    нерег.
                  </span>
                )}
                <span className="text-[11px] text-slate-400 tabular-nums w-[32px] text-right shrink-0">
                  {pct.toFixed(0)}%
                </span>
                <span className="text-sm font-semibold text-slate-700 tabular-nums w-[76px] text-right shrink-0">
                  {formatRub(item.amount)}
                </span>
              </div>
              {/* Progress bar */}
              <div className="ml-3.5 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ease-out ${barColor}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
        {items.length === 0 && (
          <div className="py-4 text-center text-sm text-slate-400">Нет данных</div>
        )}
      </div>
    </div>
  );
}

/* ── Filter Chip ────────────────────────────────────────────── */

type RegularityFilter = 'all' | 'regular' | 'irregular';
type PriorityFilter = 'all' | 'expense_essential' | 'expense_secondary';

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`rounded-lg px-3 py-1.5 transition-colors ${active ? 'bg-white text-slate-900 shadow-sm font-medium' : 'cursor-pointer hover:text-slate-700'}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

/* ── Top Expense Categories (Expanded — with period filter + transitions) ── */

function TopExpenseCategoriesExpanded({
  defaultItems,
  defaultTotal,
  installmentCards,
  transactions,
  categories,
}: {
  defaultItems: TopExpenseItem[];
  defaultTotal: number;
  installmentCards: Props['installmentCards'];
  transactions: Transaction[];
  categories: Category[];
}) {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [regFilter, setRegFilter] = useState<RegularityFilter>('all');
  const [prioFilter, setPrioFilter] = useState<PriorityFilter>('all');

  const isCurrentMonth = year === now.getFullYear() && month === now.getMonth();

  // Compute years/months from transactions
  const years = useMemo(() => {
    const yrs = getTransactionYears(transactions);
    if (!yrs.includes(now.getFullYear())) yrs.unshift(now.getFullYear());
    return yrs;
  }, [transactions]);

  const months = useMemo(() => {
    const m = getTransactionMonths(transactions, year);
    if (year === now.getFullYear() && !m.includes(now.getMonth())) m.push(now.getMonth());
    m.sort((a, b) => a - b);
    return m.length > 0 ? m : [now.getMonth()];
  }, [transactions, year]);

  // Snap month when year changes
  useEffect(() => {
    if (months.length > 0 && !months.includes(month)) {
      setMonth(months[months.length - 1]);
    }
  }, [months, month]);

  // Compute data for the selected period (all categories, not just top 5)
  const items = useMemo(
    () =>
      isCurrentMonth
        ? defaultItems
        : computeTopExpenses(transactions, categories, year, month, 50),
    [isCurrentMonth, defaultItems, transactions, categories, year, month],
  );
  const totalExpenses = useMemo(
    () => (isCurrentMonth ? defaultTotal : computeExpenseTotals(transactions, year, month)),
    [isCurrentMonth, defaultTotal, transactions, year, month],
  );

  const filtered = items.filter((item) => {
    if (regFilter === 'regular' && !item.isRegular) return false;
    if (regFilter === 'irregular' && item.isRegular) return false;
    if (prioFilter !== 'all' && item.priority !== prioFilter) return false;
    return true;
  });

  const filteredTotal = filtered.reduce((s, i) => s + i.amount, 0);

  return (
    <div>
      {/* Header */}
      <p className="text-base font-semibold text-slate-900">Категории расходов</p>
      <p className="text-xs text-slate-500 mt-0.5">Анализ расходов по категориям</p>

      {/* Period + Regularity + Priority filters */}
      <div className="mt-5 space-y-3">
        {/* Period selectors */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-400 font-medium">Период:</span>
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="text-xs rounded-lg border border-slate-200 px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
          <select
            value={month}
            onChange={(e) => setMonth(Number(e.target.value))}
            className="text-xs rounded-lg border border-slate-200 px-2 py-1.5 text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
          >
            {months.map((idx) => (
              <option key={idx} value={idx}>
                {MONTH_NAMES[idx]}
              </option>
            ))}
          </select>
        </div>

        {/* Regularity + priority filters */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl bg-slate-100 p-0.5 text-xs text-slate-500">
            <FilterChip label="Все" active={regFilter === 'all'} onClick={() => setRegFilter('all')} />
            <FilterChip label="Регулярные" active={regFilter === 'regular'} onClick={() => setRegFilter('regular')} />
            <FilterChip label="Нерегулярные" active={regFilter === 'irregular'} onClick={() => setRegFilter('irregular')} />
          </div>
          <div className="mx-1 h-5 w-px bg-slate-200" />
          <div className="inline-flex rounded-xl bg-slate-100 p-0.5 text-xs text-slate-500">
            <FilterChip label="Все" active={prioFilter === 'all'} onClick={() => setPrioFilter('all')} />
            <FilterChip label="Обязательные" active={prioFilter === 'expense_essential'} onClick={() => setPrioFilter('expense_essential')} />
            <FilterChip label="Второстепенные" active={prioFilter === 'expense_secondary'} onClick={() => setPrioFilter('expense_secondary')} />
          </div>
        </div>
      </div>

      {/* SVG Bar Chart with transitions */}
      {filtered.length > 0 &&
        (() => {
          const maxAmount = Math.max(...filtered.map((i) => i.amount), 1);
          const barGap = Math.min(100, Math.floor(600 / filtered.length));
          const chartW = Math.max(780, filtered.length * barGap + 80);

          const barFill = (status: 'spike' | 'drift' | 'normal') => {
            if (status === 'spike') return '#E24B4A';
            if (status === 'drift') return '#EF9F27';
            return '#378ADD';
          };

          return (
            <div className="mt-5 rounded-[28px] bg-slate-50/70 px-2 py-4 overflow-x-auto">
              <svg
                viewBox={`0 0 ${chartW} 340`}
                width="100%"
                height="340"
                xmlns="http://www.w3.org/2000/svg"
              >
                {[30, 78, 126, 174, 222].map((y) => (
                  <line key={y} x1="56" y1={y} x2={chartW - 20} y2={y} stroke="#E2E8F0" strokeDasharray="4 3" />
                ))}
                <line x1="56" y1={270} x2={chartW - 20} y2={270} stroke="#E2E8F0" />

                {filtered.map((item, idx) => {
                  const x = 80 + idx * barGap;
                  const pct = item.amount / maxAmount;
                  const barH = pct * 240;
                  const y = 270 - barH;
                  return (
                    <g key={item.name}>
                      <rect
                        x={x}
                        width={48}
                        rx="6"
                        ry="6"
                        fill={barFill(item.status)}
                        style={{
                          // eslint-disable-next-line @typescript-eslint/no-explicit-any
                          ...({ y, height: barH } as any),
                          transition: 'y 0.5s cubic-bezier(0.4,0,0.2,1), height 0.5s cubic-bezier(0.4,0,0.2,1)',
                        }}
                      />
                      <text x={x + 24} y={y - 10} textAnchor="middle" fill="#64748B" fontSize="11" fontWeight="500">
                        {formatRub(item.amount)}
                      </text>
                      {item.status === 'spike' && (
                        <text x={x + 24} y={y} textAnchor="middle" fill="#A32D2D" fontSize="13" fontWeight="700">
                          {'\u2191'}
                        </text>
                      )}
                      {item.status === 'drift' && (
                        <text x={x + 24} y={y} textAnchor="middle" fill="#854F0B" fontSize="13" fontWeight="700">
                          {'\u2197'}
                        </text>
                      )}
                      <text
                        x={x + 24}
                        y={292}
                        textAnchor="end"
                        fill="#64748B"
                        fontSize="11"
                        transform={`rotate(-20 ${x + 24} 292)`}
                      >
                        {item.name.length > 10 ? item.name.slice(0, 9) + '.' : item.name}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
          );
        })()}

      {filtered.length === 0 && (
        <div className="mt-5 py-8 text-center text-sm text-slate-400">Нет данных за выбранный период</div>
      )}

      {/* Legend */}
      <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded" style={{ background: '#378ADD' }} /> Норма
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded" style={{ background: '#E24B4A' }} /> Всплеск {'\u2191'}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded" style={{ background: '#EF9F27' }} /> Дрифт {'\u2197'}
        </span>
      </div>

      {/* Footer totals */}
      <div className="mt-4 border-t border-slate-100 pt-3">
        <div className="flex items-baseline justify-between">
          <span className="text-sm text-slate-500">Итого расходов</span>
          <span className="text-base font-bold text-slate-900">{formatRub(filteredTotal)}</span>
        </div>
        <div className="mt-1 flex gap-4 text-xs text-slate-400">
          <span>
            Регулярные:{' '}
            <b className="text-slate-500">
              {formatRub(filtered.filter((i) => i.isRegular).reduce((s, i) => s + i.amount, 0))}
            </b>
          </span>
          <span>
            Нерегулярные:{' '}
            <b className="text-slate-500">
              {formatRub(filtered.filter((i) => !i.isRegular).reduce((s, i) => s + i.amount, 0))}
            </b>
          </span>
        </div>
      </div>

      {/* Installment annotation */}
      {installmentCards.length > 0 && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-orange-50 px-3.5 py-2.5">
          <div className="mb-1 flex items-center gap-1.5">
            <span className="text-orange-600 text-sm">{'\u26A0'}</span>
            <span className="text-xs font-semibold text-orange-900">Рассрочки</span>
            <span className="text-xs text-orange-700">
              {formatRub(installmentCards.reduce((s, c) => s + c.monthlyPayment, 0))}/мес
            </span>
          </div>
          {installmentCards.map((card) => {
            const debt = card.remaining != null ? card.monthlyPayment * card.remaining : card.totalAmount;
            return (
              <p key={card.name} className="text-xs text-orange-800">
                {card.name}: долг {formatRub(debt)}
                {card.remaining != null && ` (ещё ${card.remaining} мес)`}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Expense Structure (collapsed view) ──────────────────────── */

function ExpenseStructureCollapsed({ data }: { data: IncomeStructureData }) {
  const items = [
    { label: 'Обязательные', amount: data.essentialSpent, color: 'bg-rose-400' },
    { label: 'Второстепенные', amount: data.secondarySpent, color: 'bg-amber-400' },
    { label: 'Остаток', amount: data.balanceRemaining, color: 'bg-emerald-400' },
  ];
  const maxAmount = Math.max(...items.map((i) => i.amount), 1);

  return (
    <div>
      <p className="text-sm font-semibold text-slate-800">Структура расходов</p>
      <p className="text-xs text-slate-400 mt-0.5">за текущий месяц</p>
      <div className="mt-3 space-y-2">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2.5">
            <span className="text-xs text-slate-500 w-[110px] shrink-0">{item.label}</span>
            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${item.color}`}
                style={{ width: `${(item.amount / maxAmount) * 100}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-slate-700 w-[70px] text-right shrink-0">
              {formatRub(item.amount)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Income Structure ────────────────────────────────────────── */

function ruleVerdict(actual: number, target: number): { label: string; tone: string } {
  const diff = actual - target;
  if (Math.abs(diff) <= 5) return { label: 'В норме', tone: 'text-emerald-600' };
  if (diff > 0) return { label: 'Выше нормы', tone: 'text-amber-600' };
  return { label: 'Ниже нормы', tone: 'text-cyan-600' };
}

const BAR_COLORS = ['bg-cyan-400', 'bg-cyan-300', 'bg-cyan-200'];

function IncomeCollapsed({ data }: { data: IncomeStructureData }) {
  const maxAmount = Math.max(...data.sources.map((s) => s.amount), 1);

  return (
    <div>
      <p className="text-sm font-semibold text-slate-800">Структура доходов</p>
      <div className="mt-3 space-y-2">
        {data.sources.map((source, idx) => (
          <div key={source.name} className="flex items-center gap-2.5">
            <span className="text-xs text-slate-500 w-[110px] truncate shrink-0">{source.name}</span>
            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${BAR_COLORS[Math.min(idx, BAR_COLORS.length - 1)]}`}
                style={{ width: `${(source.amount / maxAmount) * 100}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-slate-700 w-[70px] text-right shrink-0">
              {formatRub(source.amount)}
            </span>
          </div>
        ))}
        {data.sources.length === 0 && (
          <div className="py-4 text-center text-sm text-slate-400">Нет данных</div>
        )}
      </div>
    </div>
  );
}

function IncomeExpanded({ data }: { data: IncomeStructureData }) {
  const maxAmount = Math.max(...data.sources.map((s) => s.amount), 1);

  const rules = [
    { label: 'Обязательные (цель 50%)', target: 50, actual: data.essentialShare },
    { label: 'Второстепенные (цель 30%)', target: 30, actual: data.secondaryShare },
    { label: 'Остаток (цель 20%)', target: 20, actual: data.balanceShare },
  ];

  return (
    <div>
      <p className="text-lg font-bold text-slate-900">Структура доходов</p>
      <p className="text-sm text-slate-400 mt-1">Распределение по правилу 50/30/20</p>

      {/* Rules */}
      <div className="mt-4 space-y-3">
        {rules.map((rule) => {
          const verdict = ruleVerdict(rule.actual, rule.target);
          const barWidth = Math.min(rule.actual, 100);
          return (
            <div key={rule.label} className="rounded-2xl bg-slate-50 p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-600">{rule.label}</span>
                <span className={`text-xs font-semibold ${verdict.tone}`}>{verdict.label}</span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <span className="text-sm font-bold text-slate-700">{rule.actual.toFixed(1)}%</span>
                <div className="flex-1 h-2 bg-slate-200 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-cyan-400"
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Income sources */}
      <p className="text-sm font-semibold text-slate-800 mt-5">Источники дохода</p>
      <div className="mt-2 space-y-2">
        {data.sources.map((source, idx) => (
          <div key={source.name} className="flex items-center gap-2.5">
            <span className="text-xs text-slate-500 w-[110px] truncate shrink-0">{source.name}</span>
            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${BAR_COLORS[Math.min(idx, BAR_COLORS.length - 1)]}`}
                style={{ width: `${(source.amount / maxAmount) * 100}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-slate-700 w-[70px] text-right shrink-0">
              {formatRub(source.amount)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────────────── */

export function SectionAnalytics({
  trend,
  topExpenses,
  totalExpenses,
  incomeStructure,
  avgDailyExpense,
  installmentCards,
  transactions,
  categories,
  trendYears,
  trendYear,
  trendMonth,
  flowType,
  availableMonths,
  onTrendYearChange,
  onTrendMonthChange,
  onFlowTypeChange,
}: Props) {
  const [topExpensesOpen, setTopExpensesOpen] = useState(false);
  const [incomeOpen, setIncomeOpen] = useState(false);

  return (
    <section>
      {/* Section header */}
      <p className="text-lg font-bold text-slate-900">Аналитика</p>
      <p className="text-[13px] text-slate-400 mt-1">
        Динамика, структура расходов и ключевые аналитические показатели.
      </p>

      {/* Row 1: Trend */}
      <div className="mt-4 mb-4">
        <p className="text-base font-semibold text-slate-800 mb-3">Денежный поток</p>

        <div className="grid grid-cols-[0.72fr_1.28fr] gap-4">
          {/* Left — Trend Donut */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">
              {MONTH_NAMES[trendMonth]} {trendYear}
            </p>
            {trend ? <TrendDonut trend={trend} /> : <EmptyState text="Недостаточно данных" />}
          </div>

          {/* Right — Trend Chart with controls */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">По месяцам</p>
              <div className="flex items-center gap-2">
                <select
                  value={trendYear}
                  onChange={(e) => onTrendYearChange(Number(e.target.value))}
                  className="text-xs rounded-lg border border-slate-200 px-2 py-1 text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
                >
                  {trendYears.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
                <select
                  value={trendMonth}
                  onChange={(e) => onTrendMonthChange(Number(e.target.value))}
                  className="text-xs rounded-lg border border-slate-200 px-2 py-1 text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
                >
                  {availableMonths.map((idx) => (
                    <option key={idx} value={idx}>
                      {MONTH_NAMES[idx]}
                    </option>
                  ))}
                </select>
                <div className="inline-flex rounded-xl bg-slate-100 p-0.5 text-xs text-slate-500">
                  <button
                    type="button"
                    className={`rounded-lg px-2.5 py-1 transition-colors ${flowType === 'basic' ? 'bg-white text-slate-900 shadow-sm font-medium' : 'cursor-pointer hover:text-slate-700'}`}
                    onClick={() => onFlowTypeChange('basic')}
                  >
                    Базовый
                  </button>
                  <button
                    type="button"
                    className={`rounded-lg px-2.5 py-1 transition-colors ${flowType === 'full' ? 'bg-white text-slate-900 shadow-sm font-medium' : 'cursor-pointer hover:text-slate-700'}`}
                    onClick={() => onFlowTypeChange('full')}
                  >
                    Полный
                  </button>
                </div>
              </div>
            </div>
            {trend ? <TrendChart trend={trend} /> : <EmptyState text="Недостаточно данных" />}
          </div>
        </div>
      </div>

      {/* Row 2: Detail */}
      <div className="grid grid-cols-3 gap-4">
        {/* Top Expense Categories — spans 2 cols */}
        <div className="col-span-2">
          <ExpandableCard
            isOpen={topExpensesOpen}
            onToggle={() => setTopExpensesOpen((v) => !v)}
            expandedWidth="860px"
            collapsed={
              <TopExpenseCategoriesCollapsed
                items={topExpenses}
                totalExpenses={totalExpenses}
              />
            }
            expanded={
              <TopExpenseCategoriesExpanded
                defaultItems={topExpenses}
                defaultTotal={totalExpenses}
                installmentCards={installmentCards}
                transactions={transactions}
                categories={categories}
              />
            }
          />
        </div>

        {/* Right stacked column */}
        <div className="space-y-4">
          {/* Income Structure (expandable) */}
          {incomeStructure ? (
            <ExpandableCard
              isOpen={incomeOpen}
              onToggle={() => setIncomeOpen((v) => !v)}
              expandedWidth="600px"
              collapsed={<ExpenseStructureCollapsed data={incomeStructure} />}
              expanded={<IncomeExpanded data={incomeStructure} />}
            />
          ) : (
            <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative">
              <p className="text-sm font-semibold text-slate-800">Структура расходов</p>
              <EmptyState text="Недостаточно данных" />
            </div>
          )}

          {/* Avg Daily Expense (static) */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative">
            <p className="text-sm font-semibold text-slate-800">Средние траты в день</p>
            <p className="text-lg font-bold text-rose-600 mt-1">
              {formatRub(avgDailyExpense)} / день
            </p>
            <div
              className="mt-3 h-[60px] rounded-xl opacity-30"
              style={{
                background: 'linear-gradient(to right, #e0f2fe, #bae6fd, #7dd3fc, #38bdf8, #0ea5e9)',
              }}
            />
            <p className="text-xs text-slate-400 mt-2">За последние 30 дней</p>
          </div>
        </div>
      </div>
    </section>
  );
}
