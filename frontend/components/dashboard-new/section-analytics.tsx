'use client';

import { useState } from 'react';
import type {
  FlowType,
  TrendData,
  TopExpenseItem,
  IncomeStructureData,
} from '@/components/dashboard-new/dashboard-data';
import { formatRub, TAG_CLASSES } from '@/components/dashboard-new/dashboard-data';
import { ExpandableCard } from '@/components/dashboard-new/expandable-card';

type Props = {
  trend: TrendData | null;
  topExpenses: TopExpenseItem[];
  totalExpenses: number;
  incomeStructure: IncomeStructureData | null;
  avgDailyExpense: number;
  installmentCards: Array<{ name: string; monthlyPayment: number; remaining: number | null }>;
  // Trend controls
  trendYears: number[];
  trendYear: number;
  trendMonth: number;
  flowType: FlowType;
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

/* ── Trend Donut ─────────────────────────────────────────────── */

function TrendDonut({ trend }: { trend: TrendData }) {
  const total = trend.avgIncome + trend.avgExpense + trend.avgCreditPayments;
  const incomePct = total > 0 ? (trend.avgIncome / total) * 100 : 33;
  const expensePct = total > 0 ? (trend.avgExpense / total) * 100 : 33;
  const creditPct = total > 0 ? (trend.avgCreditPayments / total) * 100 : 34;

  const balance = trend.avgIncome - trend.avgExpense - trend.avgCreditPayments;

  const conicGradient = `conic-gradient(
    #06b6d4 0% ${incomePct}%,
    #f43f5e ${incomePct}% ${incomePct + expensePct}%,
    #94a3b8 ${incomePct + expensePct}% 100%
  )`;

  return (
    <div className="flex items-center gap-4 mt-4">
      {/* Donut */}
      <div className="relative shrink-0" style={{ width: 140, height: 140 }}>
        <div
          className="absolute inset-0 rounded-full"
          style={{ background: conicGradient }}
        />
        <div className="absolute inset-[30px] rounded-full bg-white flex flex-col items-center justify-center">
          <span className="text-[9px] font-semibold uppercase tracking-wide text-slate-400 leading-tight">Остаток</span>
          <span className="text-[16px] font-extrabold text-emerald-600 leading-tight">{formatRub(balance)}</span>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-cyan-500" />
          <div>
            <p className="text-xs text-slate-500">Доходы</p>
            <p className="text-sm font-bold text-cyan-600">{formatRub(trend.avgIncome)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-rose-500" />
          <div>
            <p className="text-xs text-slate-500">Расходы</p>
            <p className="text-sm font-bold text-rose-600">{formatRub(trend.avgExpense)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-slate-400" />
          <div>
            <p className="text-xs text-slate-500">Кредиты</p>
            <p className="text-sm font-bold text-slate-500">{formatRub(trend.avgCreditPayments)}</p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Trend Chart ─────────────────────────────────────────────── */

function TrendChart({ trend }: { trend: TrendData }) {
  const maxVal = Math.max(
    ...trend.points.map((p) => Math.max(p.income, p.expense)),
    1,
  );

  return (
    <div className="mt-3">
      <div className="flex items-end gap-1.5 h-[120px] px-2">
        {trend.points.map((p) => (
          <div key={p.key} className="flex-1 flex items-end gap-0.5 min-w-0">
            <div
              className="flex-1 rounded-t-md min-w-0 bg-cyan-200"
              style={{ height: `${(p.income / maxVal) * 100}%` }}
            />
            <div
              className="flex-1 rounded-t-md min-w-0 bg-rose-200"
              style={{ height: `${(p.expense / maxVal) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-slate-400 mt-2 px-2">
        {trend.points.map((p) => (
          <span key={p.key}>{p.label}</span>
        ))}
      </div>
    </div>
  );
}

/* ── Top Expense Categories ──────────────────────────────────── */

function TopExpenseCategoriesCollapsed({
  items,
  totalExpenses,
  installmentCards,
}: {
  items: TopExpenseItem[];
  totalExpenses: number;
  installmentCards: Props['installmentCards'];
}) {
  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-800">Топ категорий расходов</p>
          <p className="text-xs text-slate-400 mt-0.5">за текущий месяц</p>
        </div>
        <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[10px] text-slate-400 shrink-0">
          i
        </span>
      </div>

      {/* Summary */}
      <div className="mt-3 rounded-xl bg-slate-50 px-3 py-2 flex items-center justify-between">
        <span className="text-sm text-slate-500">Всего</span>
        <span className="text-sm font-semibold text-slate-700">{formatRub(totalExpenses)}</span>
      </div>

      {/* Category list */}
      <div className="mt-2 divide-y divide-slate-100">
        {items.map((item) => (
          <div key={item.name} className="flex items-center gap-2 py-2">
            {anomalyDot(item.status)}
            <span className="text-sm text-slate-800 flex-1 truncate">{item.name}</span>
            {item.isRegular ? (
              <span className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0 bg-emerald-50 text-emerald-600">
                рег.
              </span>
            ) : (
              <span className="text-[10px] rounded px-1.5 py-0.5 font-medium shrink-0 bg-amber-50 text-amber-600">
                нерег.
              </span>
            )}
            <span className="text-sm font-semibold text-slate-700 tabular-nums w-[76px] text-right shrink-0">
              {formatRub(item.amount)}
            </span>
          </div>
        ))}
        {items.length === 0 && (
          <div className="py-4 text-center text-sm text-slate-400">Нет данных</div>
        )}
      </div>

    </div>
  );
}

function TopExpenseCategoriesExpanded({
  items,
  totalExpenses,
  installmentCards,
}: {
  items: TopExpenseItem[];
  totalExpenses: number;
  installmentCards: Props['installmentCards'];
}) {
  return (
    <div>
      {/* Header */}
      <p className="text-base font-semibold text-slate-900">Категории расходов</p>
      <p className="text-xs text-slate-500 mt-0.5">Анализ расходов по категориям</p>

      {/* Filters (visual, non-interactive) */}
      <div className="mt-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-xl bg-slate-100 p-1 text-xs text-slate-500">
            <span className="rounded-lg px-3 py-1.5 bg-white text-slate-900 shadow-sm">Все</span>
            <span className="rounded-lg px-3 py-1.5 cursor-pointer hover:text-slate-700">Регулярные</span>
            <span className="rounded-lg px-3 py-1.5 cursor-pointer hover:text-slate-700">Нерегулярные</span>
          </div>
          <div className="mx-1 h-5 w-px bg-slate-200" />
          <div className="inline-flex rounded-xl bg-slate-100 p-1 text-xs text-slate-500">
            <span className="rounded-lg px-3 py-1.5 bg-white text-slate-900 shadow-sm">Все</span>
            <span className="rounded-lg px-3 py-1.5 cursor-pointer hover:text-slate-700">Обязательные</span>
            <span className="rounded-lg px-3 py-1.5 cursor-pointer hover:text-slate-700">Второстепенные</span>
          </div>
        </div>
      </div>

      {/* SVG Bar Chart */}
      {items.length > 0 && (() => {
        const maxAmount = Math.max(...items.map((i) => i.amount), 1);
        const barGap = Math.min(100, Math.floor(600 / items.length));
        const chartW = Math.max(780, items.length * barGap + 80);

        const barFill = (status: 'spike' | 'drift' | 'normal') => {
          if (status === 'spike') return '#E24B4A';
          if (status === 'drift') return '#EF9F27';
          return '#378ADD';
        };

        return (
          <div className="mt-5 rounded-[28px] bg-slate-50/70 px-2 py-4">
            <svg viewBox={`0 0 ${chartW} 340`} width="100%" height="340" xmlns="http://www.w3.org/2000/svg">
              {[30, 78, 126, 174, 222].map((y) => (
                <line key={y} x1="56" y1={y} x2={chartW - 20} y2={y} stroke="#E2E8F0" strokeDasharray="4 3" />
              ))}
              <line x1="56" y1={270} x2={chartW - 20} y2={270} stroke="#E2E8F0" />

              {items.map((item, idx) => {
                const x = 80 + idx * barGap;
                const pct = item.amount / maxAmount;
                const barH = pct * 240;
                const y = 270 - barH;
                return (
                  <g key={item.name}>
                    <rect x={x} y={y} width={48} height={barH} rx="6" ry="6" fill={barFill(item.status)} />
                    <text x={x + 24} y={y - 10} textAnchor="middle" fill="#64748B" fontSize="11" fontWeight="500">
                      {formatRub(item.amount)}
                    </text>
                    {item.status === 'spike' && (
                      <text x={x + 24} y={y} textAnchor="middle" fill="#A32D2D" fontSize="13" fontWeight="700">{'\u2191'}</text>
                    )}
                    {item.status === 'drift' && (
                      <text x={x + 24} y={y} textAnchor="middle" fill="#854F0B" fontSize="13" fontWeight="700">{'\u2197'}</text>
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
          <span className="text-base font-bold text-slate-900">{formatRub(totalExpenses)}</span>
        </div>
        <div className="mt-1 flex gap-4 text-xs text-slate-400">
          <span>Регулярные: <b className="text-slate-500">{formatRub(items.filter((i) => i.isRegular).reduce((s, i) => s + i.amount, 0))}</b></span>
          <span>Нерегулярные: <b className="text-slate-500">{formatRub(items.filter((i) => !i.isRegular).reduce((s, i) => s + i.amount, 0))}</b></span>
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
          {installmentCards.map((card) => (
            <p key={card.name} className="text-xs text-orange-800">
              {card.name}: {formatRub(card.monthlyPayment)}/мес
              {card.remaining != null && ` (ещё ${card.remaining} мес)`}
            </p>
          ))}
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
  trendYears,
  trendYear,
  trendMonth,
  flowType,
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
        {/* Header with controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <p className="text-base font-semibold text-slate-800">Денежный поток</p>
          <div className="flex items-center gap-2">
            <select
              value={trendYear}
              onChange={(e) => onTrendYearChange(Number(e.target.value))}
              className="text-xs rounded-lg border border-slate-200 px-2.5 py-1.5 text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
            >
              {trendYears.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
            <select
              value={trendMonth}
              onChange={(e) => onTrendMonthChange(Number(e.target.value))}
              className="text-xs rounded-lg border border-slate-200 px-2.5 py-1.5 text-slate-700 bg-white focus:outline-none focus:ring-1 focus:ring-slate-300"
            >
              {MONTH_NAMES.map((name, idx) => (
                <option key={idx} value={idx}>{name}</option>
              ))}
            </select>
            <div className="inline-flex rounded-xl bg-slate-100 p-0.5 text-xs text-slate-500">
              <button
                type="button"
                className={`rounded-lg px-3 py-1.5 transition-colors ${flowType === 'basic' ? 'bg-white text-slate-900 shadow-sm font-medium' : 'hover:text-slate-700'}`}
                onClick={() => onFlowTypeChange('basic')}
              >
                Базовый
              </button>
              <button
                type="button"
                className={`rounded-lg px-3 py-1.5 transition-colors ${flowType === 'full' ? 'bg-white text-slate-900 shadow-sm font-medium' : 'hover:text-slate-700'}`}
                onClick={() => onFlowTypeChange('full')}
              >
                Полный
              </button>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-[0.72fr_1.28fr] gap-4">
          {/* Left — Trend Donut */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">Средние значения</p>
            {trend ? <TrendDonut trend={trend} /> : <EmptyState text="Недостаточно данных" />}
          </div>

          {/* Right — Trend Chart */}
          <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-1">По месяцам</p>
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
                installmentCards={installmentCards}
              />
            }
            expanded={
              <TopExpenseCategoriesExpanded
                items={topExpenses}
                totalExpenses={totalExpenses}
                installmentCards={installmentCards}
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
