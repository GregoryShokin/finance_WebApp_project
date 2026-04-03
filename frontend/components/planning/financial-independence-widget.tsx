'use client';

import { useEffect, useRef, useState } from 'react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { FinancialHealth } from '@/types/financial-health';

const SCALE = 1.8;

type Props = {
  data: FinancialHealth | null | undefined;
  isLoading?: boolean;
};

function getFiZone(percent: number) {
  if (percent >= 100) {
    return { color: '#0F6E56', label: 'Свобода', badgeClass: 'bg-teal-100 text-teal-700' };
  }
  if (percent >= 50) {
    return { color: '#1D9E75', label: 'На пути', badgeClass: 'bg-emerald-100 text-emerald-700' };
  }
  if (percent >= 10) {
    return { color: '#EF9F27', label: 'Частичная', badgeClass: 'bg-amber-100 text-amber-700' };
  }
  return { color: '#E24B4A', label: 'Зависимость', badgeClass: 'bg-rose-100 text-rose-700' };
}

export function FinancialIndependenceWidget({ data, isLoading = false }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) {
      setCollapsedHeight(cardRef.current.offsetHeight);
    }
  }, [isExpanded]);

  useEffect(() => {
    if (!isExpanded) return;

    function handleClick(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) {
        setIsExpanded(false);
      }
    }

    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded]);

  const percent = data?.fi_percent ?? 0;
  const zone = getFiZone(percent);
  const avgMonthlyExpenses = data?.avg_monthly_expenses ?? ((data?.fi_capital_needed ?? 0) / 300);

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Финансовая независимость</p>
          <div className="mt-3 space-y-2">
            <div className="h-9 w-24 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-24 animate-pulse rounded-full bg-slate-100" />
            <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
          </div>
        </>
      );
    }

    if (!data) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Финансовая независимость</p>
          <div className="mt-3">
            <p className="text-3xl font-medium text-slate-300">-</p>
            <p className="mt-2 text-sm text-slate-400">Недостаточно данных</p>
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Финансовая независимость</p>

        <button
          type="button"
          onClick={() => setIsExpanded((value) => !value)}
          className="absolute right-3 top-3 flex size-[22px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
          aria-label="Подробнее"
          aria-expanded={isExpanded}
        >
          i
        </button>

        <p className="mt-2 text-3xl font-medium" style={{ color: zone.color }}>
          {percent.toFixed(1)}
          <span className="ml-1 text-base font-normal text-slate-400">%</span>
        </p>

        <span className={cn('mt-1.5 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium', zone.badgeClass)}>
          {zone.label}
        </span>

        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{ width: `${Math.min(percent, 100)}%`, backgroundColor: zone.color }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-slate-300">
            <span>0%</span>
            <span>100% (свобода)</span>
          </div>
        </div>

        {isExpanded ? (
          <>
            <hr className="my-3 border-slate-100" />

            <div className="space-y-2.5">
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-slate-500">Пассивный доход</span>
                <span className="text-sm font-medium text-slate-900">
                  {formatMoney(data.fi_passive_income)} / мес
                </span>
              </div>

              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-slate-500">Среднемес. расходы</span>
                <span className="text-sm font-medium text-slate-900">
                  {formatMoney(avgMonthlyExpenses)} / мес
                </span>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-1.5">
              {[
                { label: '<10% - зависимость', bg: 'bg-rose-100', text: 'text-rose-700' },
                { label: '10-50% - частичная', bg: 'bg-amber-100', text: 'text-amber-700' },
                { label: '50-100% - на пути', bg: 'bg-emerald-100', text: 'text-emerald-700' },
                { label: '>=100% - свобода', bg: 'bg-teal-100', text: 'text-teal-700' },
              ].map((zoneItem) => (
                <span key={zoneItem.label} className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${zoneItem.bg} ${zoneItem.text}`}>
                  {zoneItem.label}
                </span>
              ))}
            </div>

            {percent < 10 ? (
              <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                Добавь источники пассивного дохода - отметь категории транзакций как «пассивный доход»
              </div>
            ) : null}
          </>
        ) : null}
      </>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative h-full overflow-visible"
      style={{ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }}
    >
      {isExpanded ? (
        <button
          type="button"
          aria-label="Закрыть"
          onClick={() => setIsExpanded(false)}
          className="fixed inset-0 z-40 bg-black/10"
        />
      ) : null}

      <div ref={cardRef}>
        <Card
          className="relative overflow-visible p-5"
          style={{
            position: isExpanded ? 'absolute' : 'relative',
            top: 0,
            left: 0,
            right: 0,
            transform: isExpanded ? `scale(${SCALE})` : 'scale(1)',
            transformOrigin: 'center center',
            transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)',
            zIndex: isExpanded ? 50 : 1,
            overflow: 'visible',
          }}
        >
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}
