'use client';

import { useState } from 'react';
import {
  formatRub,
  formatPercent,
  TAG_CLASSES,
  type FlowMetric,
  type LoadMetric,
  type ReserveMetric,
  type AvailableFinancesData,
  type MonthProgressData,
  type SafetyBufferData,
} from '@/components/dashboard-new/dashboard-data';
import { ExpandableCard } from '@/components/dashboard-new/expandable-card';

type Props = {
  flow: FlowMetric;
  load: LoadMetric;
  reserve: ReserveMetric;
  availableFinances: AvailableFinancesData;
  monthProgress: MonthProgressData;
  safetyBuffer: SafetyBufferData;
};

const MONTH_NAMES = [
  'январь', 'февраль', 'март', 'апрель', 'май', 'июнь',
  'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь',
];

const CARD_CLASS =
  'bg-white rounded-2xl border border-slate-200 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] relative';

export function SectionMoney({
  flow,
  load,
  reserve,
  availableFinances,
  monthProgress,
  safetyBuffer,
}: Props) {
  const [availOpen, setAvailOpen] = useState(false);
  const [progressOpen, setProgressOpen] = useState(false);
  const [bufferOpen, setBufferOpen] = useState(false);

  const currentMonth = MONTH_NAMES[new Date().getMonth()];

  return (
    <>
      {/* ── Part 1: Metrics Row ───────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">
        {/* Card 1 -- Поток */}
        <div className={CARD_CLASS}>
          <div className="flex items-center justify-between">
            <span className="text-[14px] font-semibold text-slate-900">Поток</span>
            <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${TAG_CLASSES[flow.tone]}`}>
              {flow.label}
            </span>
          </div>
          <div className="text-2xl font-extrabold text-slate-900 mt-1">
            {flow.balance > 0 ? '+' : ''}{formatRub(flow.balance)}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Баланс за {currentMonth}
          </div>
        </div>

        {/* Card 2 -- Нагрузка */}
        <div className={CARD_CLASS}>
          <div className="flex items-center justify-between">
            <span className="text-[14px] font-semibold text-slate-900">Нагрузка</span>
            <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${TAG_CLASSES[load.tone]}`}>
              {load.label}
            </span>
          </div>
          <div className="text-2xl font-extrabold text-slate-900 mt-1">
            {load.dti.toFixed(1)}%
          </div>
          <div className="text-xs text-slate-400 mt-1">
            DTI — доля кредитных платежей
          </div>
        </div>

        {/* Card 3 -- Запас */}
        <div className={CARD_CLASS}>
          <div className="flex items-center justify-between">
            <span className="text-[14px] font-semibold text-slate-900">Запас</span>
            <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${TAG_CLASSES[reserve.tone]}`}>
              {reserve.label}
            </span>
          </div>
          <div className="text-2xl font-extrabold text-slate-900 mt-1">
            {reserve.months.toFixed(1)} мес.
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Финансовая подушка
          </div>
        </div>
      </div>

      {/* ── Part 2: Деньги месяца ─────────────────────────────── */}
      <div className="mb-4">
        <p className="text-lg font-bold text-slate-900">Деньги месяца</p>
        <p className="text-[13px] text-slate-400 mt-1">
          Текущая динамика доходов, расходов и качества накоплений.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        {/* ── Card 1: Доступные средства ─────────────────────── */}
        <ExpandableCard
          isOpen={availOpen}
          onToggle={() => setAvailOpen((v) => !v)}
          expandedWidth="560px"
          collapsed={
            <AvailableFinancesCollapsed data={availableFinances} />
          }
          expanded={
            <AvailableFinancesExpanded data={availableFinances} />
          }
        />

        {/* ── Card 2: Прогресс месяца ────────────────────────── */}
        <ExpandableCard
          isOpen={progressOpen}
          onToggle={() => setProgressOpen((v) => !v)}
          expandedWidth="720px"
          collapsed={
            <MonthProgressCollapsed data={monthProgress} />
          }
          expanded={
            <MonthProgressExpanded data={monthProgress} />
          }
        />

        {/* ── Card 3: Подушка безопасности ───────────────────── */}
        <ExpandableCard
          isOpen={bufferOpen}
          onToggle={() => setBufferOpen((v) => !v)}
          expandedWidth="620px"
          collapsed={
            <SafetyBufferCollapsed data={safetyBuffer} />
          }
          expanded={
            <SafetyBufferExpanded data={safetyBuffer} />
          }
        />
      </div>
    </>
  );
}

/* ================================================================
   Available Finances — Collapsed / Expanded
   ================================================================ */

function AvailableFinancesCollapsed({ data }: { data: AvailableFinancesData }) {
  return (
    <>
      <div className="text-[14px] font-semibold text-slate-900">Доступные средства</div>
      <div className="text-2xl font-extrabold text-slate-900 mt-1">{formatRub(data.total)}</div>
      <div className="mt-3 space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Наличные и карты</span>
          <span className="font-semibold text-slate-700">{formatRub(data.debitTotal)}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-500">Кредитный лимит</span>
          <span className="font-semibold text-slate-700">{formatRub(data.creditLimitTotal)}</span>
        </div>
      </div>
    </>
  );
}

function AvailableFinancesExpanded({ data }: { data: AvailableFinancesData }) {
  return (
    <div>
      <div className="text-[16px] font-semibold text-slate-900">Доступные средства</div>
      <div className="text-2xl font-extrabold text-slate-900 mt-1">{formatRub(data.total)}</div>
      <div className="text-xs text-slate-400 mt-1">
        Сумма средств на дебетовых картах и доступных кредитных лимитов
      </div>

      {/* Debit accounts */}
      <div className="mt-5">
        <div className="text-[12px] font-semibold uppercase tracking-wider text-slate-400 mb-3">
          Счета и карты
        </div>
        {data.debitAccounts.map((acc) => (
          <div
            key={acc.id}
            className="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-b-0"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600 text-sm font-bold">
                {acc.name.charAt(0)}
              </div>
              <div>
                <div className="text-sm font-medium text-slate-800">{acc.name}</div>
                <div className="text-xs text-slate-400">{acc.type}</div>
              </div>
            </div>
            <div className="text-sm font-bold text-slate-900">{formatRub(acc.balance)}</div>
          </div>
        ))}
      </div>

      {/* Credit limits */}
      {data.creditCards.length > 0 && (
        <div className="border-t border-slate-100 mt-4 pt-4">
          <div className="text-[12px] font-semibold uppercase tracking-wider text-slate-400 mb-3">
            Кредитные лимиты
          </div>
          {data.creditCards.map((card) => (
            <div
              key={card.id}
              className="flex items-center justify-between py-2.5 border-b border-slate-100 last:border-b-0"
            >
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-100 text-amber-600 text-sm font-bold">
                  {card.name.charAt(0)}
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-800">{card.name}</div>
                  <div className="text-xs text-slate-400">
                    {card.type} &bull; Лимит {formatRub(card.totalLimit)}
                  </div>
                </div>
              </div>
              <div className="text-sm font-bold text-slate-900">{formatRub(card.availableLimit)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================
   Month Progress — Collapsed / Expanded
   ================================================================ */

function ProgressBar({
  percent,
  colorOver = 'bg-amber-500',
  colorNormal = 'bg-emerald-500',
  height = 'h-2',
}: {
  percent: number;
  colorOver?: string;
  colorNormal?: string;
  height?: string;
}) {
  const fill = Math.min(percent, 100);
  const barColor = percent > 100 ? colorOver : colorNormal;
  return (
    <div className={`${height} w-full rounded-full bg-slate-100`}>
      <div
        className={`${height} rounded-full ${barColor} transition-all`}
        style={{ width: `${fill}%` }}
      />
    </div>
  );
}

function MonthProgressCollapsed({ data }: { data: MonthProgressData }) {
  return (
    <>
      <div className="flex items-center justify-between">
        <span className="text-[14px] font-semibold text-slate-900">Прогресс месяца</span>
        <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${TAG_CLASSES[data.overallTone]}`}>
          {data.overallLabel}
        </span>
      </div>
      <div className="mt-3 space-y-3">
        {/* Essential */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-slate-500">Обязательные</span>
            <span className="font-semibold text-emerald-600">{data.essentialPercent}%</span>
          </div>
          <ProgressBar percent={data.essentialPercent} />
        </div>
        {/* Secondary */}
        <div>
          <div className="flex items-center justify-between text-xs mb-1">
            <span className="text-slate-500">Второстепенные</span>
            <span className="font-semibold text-amber-600">{data.secondaryPercent}%</span>
          </div>
          <ProgressBar percent={data.secondaryPercent} />
        </div>
      </div>
      <div className="text-xs text-slate-400 mt-3">
        Прошло {data.daysPassed} из {data.daysTotal} дней ({data.dayPercent}%)
      </div>
    </>
  );
}

function MonthProgressExpanded({ data }: { data: MonthProgressData }) {
  const secondaryCategories = data.essentialCategories; // reuse available breakdown

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <div className="text-[16px] font-semibold text-slate-900">Прогресс месяца</div>
          <div className="text-xs text-slate-400 mt-1">
            Прошло {data.daysPassed} из {data.daysTotal} дней ({data.dayPercent}%)
          </div>
        </div>
        <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${TAG_CLASSES[data.overallTone]}`}>
          {data.overallLabel}
        </span>
      </div>

      {/* Essential section */}
      <div className="rounded-2xl bg-slate-50/80 p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-slate-800">Обязательные расходы</span>
          <span
            className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${
              data.essentialPercent > 100 ? TAG_CLASSES.red : TAG_CLASSES.green
            }`}
          >
            {data.essentialPercent}%
          </span>
        </div>
        <ProgressBar percent={data.essentialPercent} height="h-3" />
        <div className="flex items-center justify-between text-xs text-slate-500 mt-2">
          <span>Потрачено: {formatRub(data.essentialSpent)}</span>
          <span>План: {formatRub(data.essentialPlanned)}</span>
          <span>Остаток: {formatRub(data.essentialRemaining)}</span>
        </div>
        {data.essentialCategories.length > 0 && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
            {data.essentialCategories.map((cat) => {
              const pct = cat.planned > 0 ? Math.round((cat.spent / cat.planned) * 100) : 0;
              return (
                <div key={cat.name} className="flex items-center justify-between text-xs">
                  <span className="text-slate-600 truncate">{cat.name}</span>
                  <span className="font-medium text-slate-700 ml-2 whitespace-nowrap">
                    {formatRub(cat.spent)} / {formatRub(cat.planned)} ({pct}%)
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Secondary section */}
      <div className="rounded-2xl bg-amber-50/60 p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-semibold text-slate-800">Второстепенные расходы</span>
          <span
            className={`inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ${
              data.secondaryPercent > 100 ? TAG_CLASSES.red : TAG_CLASSES.amber
            }`}
          >
            {data.secondaryPercent}%
          </span>
        </div>
        <ProgressBar
          percent={data.secondaryPercent}
          colorNormal="bg-amber-500"
          colorOver="bg-red-500"
          height="h-3"
        />
        <div className="flex items-center justify-between text-xs text-slate-500 mt-2">
          <span>Потрачено: {formatRub(data.secondarySpent)}</span>
          <span>План: {formatRub(data.secondaryPlanned)}</span>
          <span>Остаток: {formatRub(data.secondaryRemaining)}</span>
        </div>
        {data.topOverspend && (
          <div className="mt-3 rounded-xl bg-red-50 border border-red-100 p-3 text-xs text-red-700">
            Перерасход в категории &laquo;{data.topOverspend.name}&raquo;: +{formatRub(data.topOverspend.overage)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================
   Safety Buffer — Collapsed / Expanded
   ================================================================ */

function SafetyBufferCollapsed({ data }: { data: SafetyBufferData }) {
  return (
    <>
      <div className="text-[14px] font-semibold text-slate-900">Подушка безопасности</div>
      <div className="text-2xl font-extrabold text-slate-900 mt-1">{formatRub(data.saved)}</div>
      <div className="mt-3">
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-slate-500">Прогресс к цели</span>
          <span className="font-semibold text-blue-600">{data.percent}%</span>
        </div>
        <div className="h-2 w-full rounded-full bg-slate-100">
          <div
            className="h-2 rounded-full bg-blue-500 transition-all"
            style={{ width: `${Math.min(data.percent, 100)}%` }}
          />
        </div>
      </div>
      <div className="text-xs text-slate-400 mt-2">
        Цель: {formatRub(data.target)}
      </div>
    </>
  );
}

function SafetyBufferExpanded({ data }: { data: SafetyBufferData }) {
  const recommendedMonths = 3;
  const recommendedTarget = data.avgExpense * recommendedMonths;
  const needMore = Math.max(0, recommendedTarget - data.saved);

  return (
    <div>
      <div className="text-[16px] font-semibold text-slate-900">Подушка безопасности</div>
      <div className="text-xs text-slate-400 mt-0.5">
        Накопления на случай непредвиденных расходов
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4 mt-5">
        <div className="rounded-2xl bg-blue-50 p-4 text-center">
          <div className="text-xs font-semibold uppercase tracking-wider text-blue-400">Накоплено</div>
          <div className="text-xl font-extrabold text-blue-700 mt-1">{formatRub(data.saved)}</div>
        </div>
        <div className="rounded-2xl bg-slate-50 p-4 text-center">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Цель</div>
          <div className="text-xl font-extrabold text-slate-700 mt-1">{formatRub(data.target)}</div>
        </div>
        <div className="rounded-2xl bg-emerald-50 p-4 text-center">
          <div className="text-xs font-semibold uppercase tracking-wider text-emerald-400">Ср. расходы</div>
          <div className="text-xl font-extrabold text-emerald-700 mt-1">{formatRub(data.avgExpense)}</div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mt-5">
        <div className="flex items-center justify-between text-xs mb-2">
          <span className="text-slate-500">Прогресс к цели</span>
          <span className="font-bold text-blue-600">{data.percent}%</span>
        </div>
        <div className="h-[14px] w-full rounded-full bg-slate-100 overflow-hidden">
          <div
            className="h-full rounded-full bg-blue-500 transition-all"
            style={{ width: `${Math.min(data.percent, 100)}%` }}
          />
        </div>
      </div>

      {/* Warning / recommendation */}
      <div className="mt-4 rounded-2xl bg-amber-50 border border-amber-100 p-4">
        <div className="text-sm font-semibold text-amber-800 mb-1">
          Покрытие: {data.coverageMonths.toFixed(1)} мес.
        </div>
        <div className="text-xs text-amber-700">
          {data.coverageMonths >= 3
            ? 'Ваш резерв покрывает более 3 месяцев расходов. Отличный результат!'
            : needMore > 0
              ? `Рекомендуется накопить ещё ${formatRub(needMore)} для покрытия ${recommendedMonths} месяцев расходов.`
              : 'Продолжайте наращивать резерв для большей финансовой устойчивости.'}
        </div>
      </div>
    </div>
  );
}
