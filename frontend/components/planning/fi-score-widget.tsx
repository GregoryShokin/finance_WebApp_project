'use client';

import { useEffect, useRef, useState } from 'react';
import { ShoppingCart } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { resolveExpandUp } from '@/lib/utils/widget-expand';
import type { FIScoreComponents, FinancialHealth } from '@/types/financial-health';

const SCALE = 1.8;
export const FI_SCORE_WIDGET_EVENT = 'financeapp:fi-score-widget-toggle';

type Props = {
  data: FinancialHealth | null | undefined;
  isLoading?: boolean;
  largePurchasesTotal?: number;
};

type ScoreComponentRow = {
  label: string;
  value: number;
};

function getCompColor(value: number): string {
  if (value >= 8) return '#1D9E75';
  if (value >= 5) return '#EF9F27';
  return '#E24B4A';
}

function getFiZone(score: number) {
  if (score >= 8) return { color: '#0F6E56', label: 'РЎРІРѕР±РѕРґР°', badgeClass: 'bg-teal-100 text-teal-700' };
  if (score >= 6) return { color: '#1D9E75', label: 'РџСѓС‚СЊ', badgeClass: 'bg-emerald-100 text-emerald-700' };
  if (score >= 3) return { color: '#EF9F27', label: 'Р РѕСЃС‚', badgeClass: 'bg-amber-100 text-amber-700' };
  return { color: '#E24B4A', label: 'Р РёСЃРє', badgeClass: 'bg-rose-100 text-rose-700' };
}

function buildComponents(components: FIScoreComponents): ScoreComponentRow[] {
  return [
    { label: 'РќРѕСЂРјР° СЃР±РµСЂРµР¶РµРЅРёР№', value: components.savings_rate },
    { label: 'Р”РёСЃС†РёРїР»РёРЅР°', value: components.discipline },
    { label: 'Р¤РёРЅ. РЅРµР·Р°РІРёСЃРёРјРѕСЃС‚СЊ', value: components.financial_independence },
    { label: 'Подушка безопасности', value: components.safety_buffer },
    { label: 'РљСЂРµРґРёС‚РЅР°СЏ РЅР°РіСЂСѓР·РєР°', value: components.dti_inverse },
  ];
}

export function FiScoreWidget({ data, isLoading = false, largePurchasesTotal = 0 }: Props) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);
  const [expandUp, setExpandUp] = useState(false);

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

  useEffect(() => {
    function handleExternalToggle(event: Event) {
      const customEvent = event as CustomEvent<{ source?: string; open?: boolean }>;
      if (customEvent.detail?.source !== 'fi-score-widget' && customEvent.detail?.open) {
        setIsExpanded(false);
      }
    }

    document.addEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
    return () => document.removeEventListener(FI_SCORE_WIDGET_EVENT, handleExternalToggle as EventListener);
  }, []);

  const score = data?.fi_score ?? 0;
  const zone = getFiZone(score);
  const componentRows = data ? buildComponents(data.fi_score_components) : [];
  const worstComponent = componentRows.length > 0 ? [...componentRows].sort((left, right) => left.value - right.value)[0] : null;
  const history = data?.fi_score_components.history;

  function handleToggle() {
    if (!isExpanded && cardRef.current) {
      setExpandUp(resolveExpandUp(cardRef.current, 400));
    }
    setIsExpanded((current) => {
      const next = !current;
      document.dispatchEvent(
        new CustomEvent(FI_SCORE_WIDGET_EVENT, {
          detail: { source: 'fi-score-widget', open: next },
        }),
      );
      return next;
    });
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">FI-score</p>
          <div className="mt-3 space-y-2">
            <div className="h-9 w-24 animate-pulse rounded bg-slate-100" />
            <div className="h-5 w-20 animate-pulse rounded-full bg-slate-100" />
            <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
          </div>
        </>
      );
    }

    if (!data) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">FI-score</p>
          <div className="mt-3">
            <p className="text-3xl font-medium text-slate-300">-</p>
            <p className="mt-2 text-sm text-slate-400">РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РґР°РЅРЅС‹С…</p>
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">FI-score</p>

        <button
          type="button"
          onClick={handleToggle}
          className="absolute right-3 top-3 flex size-[22px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white"
          aria-label="РџРѕРґСЂРѕР±РЅРµРµ"
          aria-expanded={isExpanded}
        >
          i
        </button>

        <p className="mt-2 text-3xl font-medium" style={{ color: zone.color }}>
          {score.toFixed(1)}
          <span className="ml-1 text-base font-normal text-slate-400">/ 10</span>
        </p>

        <span className={cn('mt-1.5 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium', zone.badgeClass)}>
          {zone.label}
        </span>

        <div className="mt-3">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{ width: `${(score / 10) * 100}%`, backgroundColor: zone.color }}
            />
          </div>
          <div className="mt-1 flex h-1 overflow-hidden rounded-full">
            <div className="flex-[3] bg-rose-100" />
            <div className="flex-[3] bg-amber-100" />
            <div className="flex-[2] bg-emerald-100" />
            <div className="flex-[2] bg-teal-100" />
          </div>
          <div className="mt-0.5 flex justify-between text-[9px] text-slate-300">
            <span>Р РёСЃРє</span>
            <span>Р РѕСЃС‚</span>
            <span>РџСѓС‚СЊ</span>
            <span>РЎРІРѕР±РѕРґР°</span>
          </div>
        </div>

        {isExpanded ? (
          <>
            <hr className="my-3 border-slate-100" />

            <p className="mb-2.5 text-[11px] font-medium uppercase tracking-wider text-slate-400">
              РР· С‡РµРіРѕ СЃРєР»Р°РґС‹РІР°РµС‚СЃСЏ
            </p>

            {componentRows.map(({ label, value }) => {
              const color = getCompColor(value);
              return (
                <div key={label} className="mb-2 flex items-center gap-2">
                  <span className="w-[140px] shrink-0 text-xs text-slate-500">{label}</span>
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${value * 10}%`, backgroundColor: color }}
                    />
                  </div>
                  <span className="w-8 shrink-0 text-right text-xs font-medium" style={{ color }}>
                    {value.toFixed(1)}
                  </span>
                </div>
              );
            })}

            {worstComponent ? (
              <div className="mt-2.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                Р“Р»Р°РІРЅС‹Р№ СЂС‹С‡Р°Рі СЂРѕСЃС‚Р° - СѓР»СѓС‡С€РёС‚СЊ В«{worstComponent.label}В»
              </div>
            ) : null}

            {history ? (
              <div className="mt-2.5 grid gap-2 text-xs text-slate-500 sm:grid-cols-3">
                <div className="rounded-lg bg-slate-50 px-3 py-2">Р’Р°Р·Р°: <span className="font-semibold text-slate-900">{history.baseline.toFixed(1)}</span></div>
                <div className="rounded-lg bg-slate-50 px-3 py-2">РџСЂРѕС€Р»С‹Р№: <span className="font-semibold text-slate-900">{history.previous.toFixed(1)}</span></div>
                <div className="rounded-lg bg-slate-50 px-3 py-2">РЎРµР№С‡Р°СЃ: <span className="font-semibold text-slate-900">{history.current.toFixed(1)}</span></div>
              </div>
            ) : null}

            {largePurchasesTotal > 0 ? (
              <div className="mt-2.5 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
                <ShoppingCart className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
                <p className="text-xs text-amber-700">
                  Показатели рассчитаны без крупных покупок на{' '}
                  <span className="font-medium">{formatMoney(largePurchasesTotal)}</span> за 6 месяцев.{' '}
                  <a href="/large-purchases" className="underline underline-offset-2 hover:text-amber-900">
                    Подробнее
                  </a>
                  .
                </p>
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
          aria-label="Р—Р°РєСЂС‹С‚СЊ"
          onClick={handleToggle}
          className="fixed inset-0 z-40 bg-slate-950/10"
        />
      ) : null}

      <div ref={cardRef}>
        <Card
          className="relative overflow-visible p-5"
          style={{
            position: isExpanded ? 'absolute' : 'relative',
            top: isExpanded && !expandUp ? 0 : 'auto',
            bottom: isExpanded && expandUp ? 0 : 'auto',
            left: 0,
            right: 0,
            transform: isExpanded ? `scale(${SCALE})` : 'scale(1)',
            transformOrigin: expandUp ? 'center bottom' : 'center center',
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
