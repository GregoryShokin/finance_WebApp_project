'use client';

import { useState } from 'react';

import type { CapitalData, DebtsData } from '@/components/dashboard-new/dashboard-data';
import { formatRub, formatPercent, TAG_CLASSES, toNum } from '@/components/dashboard-new/dashboard-data';
import { ExpandableCard } from '@/components/dashboard-new/expandable-card';
import type { FinancialHealth } from '@/types/financial-health';

type Props = {
  capital: CapitalData;
  debts: DebtsData;
  health: FinancialHealth;
};

// ── Helpers ──────────────────────────────────────────────────────

function initials(name: string) {
  return name.slice(0, 2);
}

const ASSET_TYPE_LABELS: Record<string, string> = {
  real_estate: 'Недвижимость',
  car: 'Авто',
  other: 'Прочее',
};

// ── Capital Card ─────────────────────────────────────────────────

function CapitalCard({ capital }: { capital: CapitalData }) {
  const [capitalMode, setCapitalMode] = useState<'liquid' | 'net'>('liquid');
  const [isOpen, setIsOpen] = useState(false);

  const value = capitalMode === 'liquid' ? capital.liquidCapital : capital.netCapital;
  const valueColor = value >= 0 ? 'text-emerald-600' : 'text-rose-600';

  const totalAssets = capital.totalAssets;
  const totalDebt = capital.totalDebt;

  // Group real assets by type
  const realAssetsByType = capital.realAssets.reduce<Record<string, number>>((acc, a) => {
    const type = a.asset_type ?? 'other';
    acc[type] = (acc[type] ?? 0) + Math.max(0, toNum(a.estimated_value));
    return acc;
  }, {});

  const pillToggle = (
    <div
      className="inline-flex rounded-full bg-slate-100 p-0.5 text-[11px]"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        className={`rounded-full px-2.5 py-1 font-medium ${
          capitalMode === 'liquid'
            ? 'bg-white text-slate-900 shadow-sm'
            : 'text-slate-500'
        }`}
        onClick={(e) => {
          e.stopPropagation();
          setCapitalMode('liquid');
        }}
      >
        Ликвидный
      </button>
      <button
        type="button"
        className={`rounded-full px-2.5 py-1 font-medium ${
          capitalMode === 'net'
            ? 'bg-white text-slate-900 shadow-sm'
            : 'text-slate-500'
        }`}
        onClick={(e) => {
          e.stopPropagation();
          setCapitalMode('net');
        }}
      >
        Чистый
      </button>
    </div>
  );

  const collapsed = (
    <div>
      <div className="flex items-center gap-3 mb-2">
        <span className="text-sm font-semibold text-slate-900">Капитал</span>
        {pillToggle}
      </div>
      <p className={`text-2xl font-extrabold ${valueColor}`}>{formatRub(value)}</p>
      <div className="grid grid-cols-2 gap-4 mt-4">
        {/* Assets */}
        <div>
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Активы
          </p>
          <div className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-slate-600">Счета и вклады</span>
              <span className="font-medium text-slate-900">
                {formatRub(capital.liquidTotal + capital.depositTotal)}
              </span>
            </div>
            {capitalMode === 'net' && (
              <>
                {Object.entries(realAssetsByType).map(
                  ([type, val]) =>
                    val > 0 && (
                      <div key={type} className="flex justify-between text-sm">
                        <span className="text-slate-600">
                          {ASSET_TYPE_LABELS[type] ?? type}
                        </span>
                        <span className="font-medium text-slate-900">
                          {formatRub(val)}
                        </span>
                      </div>
                    ),
                )}
              </>
            )}
          </div>
        </div>
        {/* Liabilities */}
        <div>
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
            Обязательства
          </p>
          <div className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-slate-600">Кредиты</span>
              <span className="font-medium text-rose-600">
                {formatRub(totalDebt)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const expanded = (
    <div>
      <div className="flex items-center gap-3 mb-2">
        <span className="text-sm font-semibold text-slate-900">Капитал</span>
        {pillToggle}
      </div>
      <p className={`text-2xl font-extrabold ${valueColor}`}>{formatRub(value)}</p>

      <div className="grid grid-cols-2 gap-6 mt-6">
        {/* Assets column */}
        <div>
          <p className="text-xs font-semibold text-emerald-500 uppercase tracking-wider mb-3">
            Активы — {formatRub(totalAssets)}
          </p>
          <div className="space-y-2">
            {capital.liquidTotal > 0 && (
              <div className="p-3 rounded-xl bg-emerald-50/60">
                <p className="text-xs text-slate-500">Ликвидные средства</p>
                <p className="text-sm font-bold text-slate-900">
                  {formatRub(capital.liquidTotal)}
                </p>
                <p className="text-[11px] text-slate-400">
                  Дебетовые карты и наличные
                </p>
              </div>
            )}
            {capital.depositTotal > 0 && (
              <div className="p-3 rounded-xl bg-emerald-50/60">
                <p className="text-xs text-slate-500">Вклады</p>
                <p className="text-sm font-bold text-slate-900">
                  {formatRub(capital.depositTotal)}
                </p>
                <p className="text-[11px] text-slate-400">Банковские депозиты</p>
              </div>
            )}
            {Object.entries(realAssetsByType).map(
              ([type, val]) =>
                val > 0 && (
                  <div key={type} className="p-3 rounded-xl bg-emerald-50/60">
                    <p className="text-xs text-slate-500">
                      {ASSET_TYPE_LABELS[type] ?? type}
                    </p>
                    <p className="text-sm font-bold text-slate-900">
                      {formatRub(val)}
                    </p>
                    <p className="text-[11px] text-slate-400">
                      Оценочная стоимость
                    </p>
                  </div>
                ),
            )}
          </div>
        </div>

        {/* Liabilities column */}
        <div>
          <p className="text-xs font-semibold text-rose-500 uppercase tracking-wider mb-3">
            Обязательства — {formatRub(totalDebt)}
          </p>
          <div className="space-y-2">
            {capital.creditAccounts.map((cr) => (
              <div key={cr.name} className="p-3 rounded-xl bg-rose-50/60">
                <p className="text-xs text-slate-500">{cr.name}</p>
                <p className="text-sm font-bold text-slate-900">
                  {formatRub(cr.balance)}
                </p>
                <p className="text-[11px] text-slate-400">
                  {cr.rate != null && `${cr.rate}% `}
                  {cr.remaining != null && `${cr.remaining} мес.`}
                </p>
              </div>
            ))}
            {capital.creditCards.map((cc) => (
              <div key={cc.name} className="p-3 rounded-xl bg-rose-50/60">
                <p className="text-xs text-slate-500">{cc.name}</p>
                <p className="text-sm font-bold text-slate-900">
                  {formatRub(cc.used)} / {formatRub(cc.limit)}
                </p>
                <p className="text-[11px] text-slate-400">
                  Использование {cc.utilization.toFixed(0)}%
                </p>
              </div>
            ))}
          </div>

          {/* Summary box */}
          <div className="mt-4 p-3 rounded-xl bg-slate-50 border border-slate-200">
            <div className="space-y-1 text-sm">
              <div className="flex justify-between">
                <span className="text-slate-500">Активы</span>
                <span className="font-medium text-emerald-600">
                  {formatRub(totalAssets)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Обязательства</span>
                <span className="font-medium text-rose-600">
                  {formatRub(totalDebt)}
                </span>
              </div>
              <div className="flex justify-between border-t border-slate-200 pt-1">
                <span className="font-semibold text-slate-700">
                  Чистый капитал
                </span>
                <span
                  className={`font-bold ${
                    capital.netCapital >= 0
                      ? 'text-emerald-600'
                      : 'text-rose-600'
                  }`}
                >
                  {formatRub(capital.netCapital)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="col-span-2">
      <ExpandableCard
        isOpen={isOpen}
        onToggle={() => setIsOpen((o) => !o)}
        expandedWidth="760px"
        collapsed={collapsed}
        expanded={expanded}
      />
    </div>
  );
}

// ── Debts Card ───────────────────────────────────────────────────

function DebtsCard({ debts }: { debts: DebtsData }) {
  const [isOpen, setIsOpen] = useState(false);

  const collapsed = (
    <div>
      <p className="text-sm font-semibold text-slate-900">Долги</p>
      <p className="text-lg font-bold text-rose-600 mt-1">
        {formatRub(debts.payableTotal)}
      </p>
      <div className="mt-2 space-y-1.5">
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Мне должны</span>
          <span className="font-semibold text-emerald-600">
            {formatRub(debts.receivableTotal)}
          </span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-slate-500">Я должен</span>
          <span className="font-semibold text-rose-500">
            {formatRub(debts.payableTotal)}
          </span>
        </div>
      </div>
    </div>
  );

  const expanded = (
    <div>
      <p className="text-base font-semibold text-slate-900 mb-4">Долги</p>

      {/* Receivables */}
      {debts.receivables.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold text-emerald-500 uppercase tracking-wider mb-3">
            Мне должны
          </p>
          <div className="space-y-2">
            {debts.receivables.map((r) => (
              <div key={r.name} className="flex items-center gap-3">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-xs font-semibold text-emerald-600">
                  {initials(r.name)}
                </div>
                <span className="text-sm text-slate-700 flex-1">{r.name}</span>
                <span className="text-sm font-semibold text-emerald-600">
                  {formatRub(r.amount)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Payables */}
      {debts.payables.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold text-rose-500 uppercase tracking-wider mb-3">
            Я должен
          </p>
          <div className="space-y-2">
            {debts.payables.map((p) => (
              <div key={p.name} className="flex items-center gap-3">
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-rose-100 text-xs font-semibold text-rose-600">
                  {initials(p.name)}
                </div>
                <span className="text-sm text-slate-700 flex-1">{p.name}</span>
                <span className="text-sm font-semibold text-rose-500">
                  {formatRub(p.amount)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      <div className="p-3 rounded-xl bg-slate-50 border border-slate-200">
        <div className="space-y-1 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-500">Мне должны</span>
            <span className="font-medium text-emerald-600">
              {formatRub(debts.receivableTotal)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-500">Я должен</span>
            <span className="font-medium text-rose-500">
              {formatRub(debts.payableTotal)}
            </span>
          </div>
          <div className="flex justify-between border-t border-slate-200 pt-1">
            <span className="font-semibold text-slate-700">Нетто-позиция</span>
            <span
              className={`font-bold ${
                debts.netPosition >= 0 ? 'text-emerald-600' : 'text-rose-600'
              }`}
            >
              {formatRub(debts.netPosition)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <ExpandableCard
      isOpen={isOpen}
      onToggle={() => setIsOpen((o) => !o)}
      expandedWidth="560px"
      collapsed={collapsed}
      expanded={expanded}
    />
  );
}

// ── Credits Card ─────────────────────────────────────────────────

function CreditsCard({
  capital,
  health,
}: {
  capital: CapitalData;
  health: FinancialHealth;
}) {
  const [isOpen, setIsOpen] = useState(false);

  const totalCreditDebt =
    capital.creditAccounts.reduce((s, c) => s + c.balance, 0) +
    capital.creditCards.reduce((s, c) => s + c.used, 0);

  const avgUtilization =
    capital.creditCards.length > 0
      ? capital.creditCards.reduce((s, c) => s + c.utilization, 0) /
        capital.creditCards.length
      : 0;

  const ringPct = Math.min(100, Math.max(0, avgUtilization));

  const collapsed = (
    <div>
      <p className="text-sm font-semibold text-slate-900">Кредиты</p>
      <p className="text-lg font-bold mt-1">{formatRub(totalCreditDebt)}</p>
      <div className="flex items-center gap-2 mt-2">
        {/* Progress ring */}
        <div className="relative size-12 shrink-0">
          <div
            className="size-full rounded-full"
            style={{
              background: `conic-gradient(#3b82f6 0% ${ringPct}%, #e2e8f0 ${ringPct}% 100%)`,
            }}
          >
            <div className="absolute inset-1.5 rounded-full bg-white" />
          </div>
          <span className="absolute inset-0 flex items-center justify-center text-[11px] font-bold text-slate-700 z-[1]">
            {Math.round(ringPct)}%
          </span>
        </div>
        <div className="text-xs text-slate-500">
          <p>Использование лимита</p>
          <p className="font-semibold text-slate-700">
            DTI {health.dti.toFixed(1)}%
          </p>
        </div>
      </div>
    </div>
  );

  const expanded = (
    <div>
      <p className="text-base font-semibold text-slate-900 mb-4">Кредиты и кре��итные карты</p>

      {/* Credit accounts */}
      {capital.creditAccounts.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Кредиты
          </p>
          <div className="space-y-3">
            {capital.creditAccounts.map((cr) => (
              <div
                key={cr.name}
                className="rounded-2xl bg-slate-50 p-4"
              >
                <p className="text-sm font-semibold text-slate-900 mb-2">
                  {cr.name}
                </p>
                <p className="text-lg font-bold text-slate-900">
                  {formatRub(cr.balance)}
                </p>
                <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
                  <div>
                    <p className="text-slate-400">Ставка</p>
                    <p className="font-semibold text-slate-700">
                      {cr.rate != null ? `${cr.rate}%` : '—'}
                    </p>
                  </div>
                  <div>
                    <p className="text-slate-400">Платёж/мес</p>
                    <p className="font-semibold text-slate-700">—</p>
                  </div>
                  <div>
                    <p className="text-slate-400">Осталось</p>
                    <p className="font-semibold text-slate-700">
                      {cr.remaining != null ? `${cr.remaining} мес.` : '—'}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Credit cards */}
      {capital.creditCards.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Кредитные карты
          </p>
          <div className="space-y-3">
            {capital.creditCards.map((cc) => (
              <div key={cc.name} className="rounded-2xl bg-slate-50 p-4">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-sm font-semibold text-slate-900">
                    {cc.name}
                  </p>
                  <p className="text-xs text-slate-500">
                    {cc.utilization.toFixed(0)}%
                  </p>
                </div>
                <p className="text-sm text-slate-700 mb-2">
                  {formatRub(cc.used)} / {formatRub(cc.limit)}
                </p>
                {/* Utilization bar */}
                <div className="h-1.5 rounded-full bg-slate-200">
                  <div
                    className="h-full rounded-full bg-blue-500 transition-all"
                    style={{ width: `${Math.min(100, cc.utilization)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* DTI block */}
      <div className="mt-5 p-4 rounded-2xl bg-blue-50 border border-blue-100">
        <p className="text-sm font-semibold text-blue-800">Кредитная нагрузка (DTI)</p>
        <div className="flex items-center gap-4 mt-3">
          <div className="text-center">
            <p className="text-3xl font-extrabold text-blue-700">
              {health.dti.toFixed(1)}%
            </p>
            <p className="text-xs text-blue-500 mt-0.5">от дохода</p>
          </div>
          <div className="flex-1 text-xs text-blue-600 space-y-1">
            <p>Ежемесячные платежи: <strong>{formatRub(health.dti_total_payments)}</strong></p>
            <p>Средний доход: <strong>{formatRub(health.dti_income)}</strong></p>
            <p className="text-blue-500 mt-1">
              {health.dti_zone === 'normal' && '\u2713 Нагрузка низкая (до 20% — безопасно)'}
              {health.dti_zone === 'acceptable' && '\u26A0 Нагрузка допустимая (20-40%)'}
              {health.dti_zone === 'dangerous' && '\u26A0 Нагрузка высокая (40-60%)'}
              {health.dti_zone === 'critical' && '\u2716 Нагрузка критическая (более 60%)'}
            </p>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <ExpandableCard
      isOpen={isOpen}
      onToggle={() => setIsOpen((o) => !o)}
      expandedWidth="620px"
      collapsed={collapsed}
      expanded={expanded}
    />
  );
}

// ── Section ──────────────────────────────────────────────────────

export function SectionCapital({ capital, debts, health }: Props) {
  return (
    <section>
      <div className="mb-4">
        <p className="text-lg font-bold text-slate-900">Капитал и долги</p>
        <p className="text-[13px] text-slate-400 mt-1">
          Структура активов, обязательств и кредитной нагрузки.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <CapitalCard capital={capital} />

        <div className="space-y-4">
          <DebtsCard debts={debts} />
          <CreditsCard capital={capital} health={health} />
        </div>
      </div>
    </section>
  );
}
