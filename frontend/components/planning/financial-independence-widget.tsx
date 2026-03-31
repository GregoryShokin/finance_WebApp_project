'use client';

import { useEffect, useRef, useState } from 'react';
import { Info, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { FinancialIndependenceMetric } from '@/types/metrics';

// ── Level config ──────────────────────────────────────────────────────────────

type Level = {
  label: string;
  text: string;
  bar: string;
  badge: string;
};

function getLevel(percent: number): Level {
  if (percent >= 100) return { label: 'Финансовая независимость достигнута', text: 'text-emerald-600', bar: 'bg-emerald-500', badge: 'bg-emerald-100 text-emerald-700' };
  if (percent >= 75)  return { label: 'На пороге независимости',             text: 'text-emerald-500', bar: 'bg-emerald-400', badge: 'bg-emerald-50 text-emerald-600'  };
  if (percent >= 50)  return { label: 'Финансовая устойчивость',             text: 'text-teal-600',    bar: 'bg-teal-500',    badge: 'bg-teal-100 text-teal-700'       };
  if (percent >= 25)  return { label: 'Уверенный рост',                      text: 'text-amber-600',   bar: 'bg-amber-400',   badge: 'bg-amber-100 text-amber-700'     };
  if (percent >= 10)  return { label: 'Формирование базы',                   text: 'text-orange-500',  bar: 'bg-orange-400',  badge: 'bg-orange-50 text-orange-600'    };
  return                     { label: 'Начальный уровень',                   text: 'text-slate-500',   bar: 'bg-slate-300',   badge: 'bg-slate-100 text-slate-600'     };
}

const SCALE = 2.4;

// ── Types ─────────────────────────────────────────────────────────────────────

type Props = {
  data: FinancialIndependenceMetric | null | undefined;
  isLoading?: boolean;
};

// ── Component ─────────────────────────────────────────────────────────────────

export function FinancialIndependenceWidget({ data, isLoading }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [cardSize, setCardSize] = useState({ width: 0, height: 0 });

  const wrapperRef     = useRef<HTMLDivElement>(null);
  const placeholderRef = useRef<HTMLDivElement>(null);

  // Measure placeholder size, update on resize
  useEffect(() => {
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setCardSize({ width, height });
    });
    if (placeholderRef.current) observer.observe(placeholderRef.current);
    return () => observer.disconnect();
  }, []);

  // Close on outside click
  useEffect(() => {
    if (!isExpanded) return;
    function handleClick(e: MouseEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) {
        setIsExpanded(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded]);

  const level = data ? getLevel(data.percent) : null;

  // ── Shared card content ───────────────────────────────────────────────────

  function renderContent() {
    return (
      <>
        {/* Title + button */}
        <div className="flex items-start justify-between gap-1">
          <p className="text-xs font-medium text-slate-500">Финансовая независимость</p>
          {data && (
            <button
              type="button"
              aria-label={isExpanded ? 'Закрыть' : 'Подробнее'}
              aria-expanded={isExpanded}
              onClick={() => setIsExpanded((v) => !v)}
              className="ml-1 flex size-5 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            >
              {isExpanded
                ? <XCircle className="size-3.5" />
                : <Info className="size-3.5" />
              }
            </button>
          )}
        </div>

        {/* Body */}
        {isLoading ? (
          <div className="mt-2 space-y-2">
            <div className="h-7 w-16 animate-pulse rounded bg-slate-100" />
            <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
            <div className="h-5 w-28 animate-pulse rounded-full bg-slate-100" />
          </div>
        ) : !data ? (
          <div className="mt-2 space-y-1">
            <p className="text-xl font-semibold text-slate-400">—</p>
            <p className="text-xs text-slate-400">Недостаточно данных</p>
          </div>
        ) : (
          <>
            {/* Summary — always visible */}
            <div className="mt-1 space-y-1.5">
              <p className={cn('text-2xl font-bold tabular-nums', level!.text)}>
                {data.percent.toFixed(0)}%
              </p>

              <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className={cn('h-full rounded-full transition-all duration-500', level!.bar)}
                  style={{ width: `${Math.min(data.percent, 100)}%` }}
                />
              </div>

              <p className={cn('inline-block rounded-full px-2 py-0.5 text-xs font-medium', level!.badge)}>
                {level!.label}
              </p>

              {/* Progress bar — collapsed state only */}
              {!isExpanded && (
                <div className="mt-2 h-1 w-full overflow-hidden rounded-sm bg-gray-200">
                  <div
                    className="h-full rounded-sm bg-green-500 transition-all duration-500"
                    style={{ width: `${Math.min(data.percent, 100)}%` }}
                  />
                </div>
              )}
            </div>

            {/* Details — visible only when expanded */}
            {isExpanded && (
              <div className="mt-3">
                <div className="h-px bg-slate-100" />
                <div className="mt-2 space-y-1.5">

                  <div className="flex items-center justify-between gap-4">
                    <span className="whitespace-nowrap text-xs text-slate-500">Пассивный доход сейчас</span>
                    <span className="whitespace-nowrap text-xs font-medium text-slate-700">
                      {formatMoney(data.passive_income)}/мес
                    </span>
                  </div>

                  <div className="flex items-center justify-between gap-4">
                    <span className="whitespace-nowrap text-xs text-slate-500">
                      Средние расходы (за {data.months_of_data} мес)
                    </span>
                    <span className="whitespace-nowrap text-xs font-medium text-slate-700">
                      {formatMoney(data.avg_expenses)}/мес
                    </span>
                  </div>

                  {data.gap > 0 && (
                    <div className="flex items-center justify-between gap-4">
                      <span className="whitespace-nowrap text-xs text-slate-500">До 100% не хватает</span>
                      <span className="whitespace-nowrap text-xs font-medium text-rose-500">
                        {formatMoney(data.gap)}/мес
                      </span>
                    </div>
                  )}

                  {data.months_of_data < 3 && (
                    <p className="rounded-lg bg-slate-50 px-3 py-2 text-center text-xs text-slate-500">
                      Данных {data.months_of_data} из 3 месяцев — метрика уточнится
                    </p>
                  )}

                </div>
              </div>
            )}
          </>
        )}
      </>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div ref={wrapperRef} className="relative h-full">

      {/* Placeholder: holds layout space, invisible but present in flow */}
      <div
        ref={placeholderRef}
        className="surface-panel p-5 h-full"
        style={{ visibility: 'hidden' }}
        aria-hidden="true"
      >
        {renderContent()}
      </div>

      {/* Real card: absolute, centered over placeholder, scales from center */}
      {cardSize.width > 0 && (
        <div
          className="surface-panel p-5"
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            width: cardSize.width,
            height: cardSize.height,
            transform: isExpanded
              ? `translate(-50%, -50%) scale(${SCALE})`
              : 'translate(-50%, -50%) scale(1)',
            transformOrigin: 'center center',
            transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)',
            zIndex: isExpanded ? 20 : 1,
            overflow: 'visible',
          }}
        >
          {renderContent()}
        </div>
      )}

    </div>
  );
}
