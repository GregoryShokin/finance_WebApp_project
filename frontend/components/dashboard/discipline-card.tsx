'use client';

import { useEffect, useRef, useState } from 'react';

import { disciplineTone } from '@/components/dashboard/card-tones';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import type { FinancialHealth } from '@/types/financial-health';

const SCALE = 1.8;
const ARC_LENGTH = 157;

function getGaugeColor(value: number | null): string {
  if (value === null) return '#B4B2A9';
  if (value < 60) return '#E24B4A';
  if (value < 80) return '#EF9F27';
  if (value <= 95) return '#1D9E75';
  return '#0F6E56';
}

function Gauge({ value, color }: { value: number; color: string }) {
  const normalized = Math.min(Math.max(value, 0), 100);
  const targetOffset = ARC_LENGTH - (normalized / 100) * ARC_LENGTH;
  const [dashOffset, setDashOffset] = useState(ARC_LENGTH);

  useEffect(() => {
    setDashOffset(targetOffset);
  }, [targetOffset]);

  return (
    <div className="mt-3">
      <svg viewBox="0 0 120 70" className="mx-auto h-[72px] w-full max-w-[180px]">
        <path d="M14,62 A46,46 0 0,1 106,62" fill="none" stroke="#F1EFE8" strokeWidth="14" strokeLinecap="round" />
        <path d="M14,62 A46,46 0 0,1 106,62" fill="none" stroke={color} strokeWidth="14" strokeLinecap="round" strokeDasharray={ARC_LENGTH} strokeDashoffset={dashOffset} style={{ transition: 'stroke-dashoffset 800ms ease' }} />
        <text x="60" y="56" textAnchor="middle" className="fill-slate-800 text-[16px] font-semibold">{value.toFixed(1)}%</text>
      </svg>
      <p className="mt-1 text-center text-[10px] text-[#B4B2A9]">соблюдение лимитов</p>
    </div>
  );
}

export function DisciplineCard({ health, isExpanded, onToggle }: { health: FinancialHealth; isExpanded: boolean; onToggle: () => void }) {
  const [collapsedHeight, setCollapsedHeight] = useState<number>(0);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (cardRef.current && !isExpanded) setCollapsedHeight(cardRef.current.offsetHeight);
  }, [isExpanded]);

  useEffect(() => {
    if (!isExpanded) return;
    function handleClick(event: MouseEvent) {
      if (!wrapperRef.current?.contains(event.target as Node)) onToggle();
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded, onToggle]);

  const tone = disciplineTone(health.discipline_zone ?? 'weak');
  const gaugeColor = getGaugeColor(health.discipline);
  const worstViolation = health.discipline_violations[0];
  const tip = worstViolation
    ? `Категория «${worstViolation.category_name}» превышает лимит ${worstViolation.months_count} мес. подряд - скорректируй лимит или сократи расходы`
    : (health.discipline ?? 0) < 60
      ? 'Выставьте лимиты в разделе Бюджет'
      : 'Хорошая дисциплина - продолжай в том же духе';

  return (
    <div ref={wrapperRef} className="relative h-full overflow-visible" style={{ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }}>
      {isExpanded ? <button type="button" aria-label="Закрыть" onClick={onToggle} className="fixed inset-0 z-40 bg-black/10" /> : null}
      <div ref={cardRef}>
        <Card className="relative overflow-visible p-5" style={{ position: isExpanded ? 'absolute' : 'relative', top: 0, left: 0, right: 0, transform: isExpanded ? `scale(${SCALE})` : 'scale(1)', transformOrigin: 'center center', transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)', zIndex: isExpanded ? 50 : 1, overflow: 'visible' }}>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Финансовая дисциплина</p>
          <button type="button" onClick={onToggle} className="absolute right-3 top-3 flex size-[22px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white" aria-label="Подробнее" aria-expanded={isExpanded}>i</button>
          <span className={cn('mt-2 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium', tone === 'good' ? 'bg-emerald-100 text-emerald-700' : tone === 'warning' ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700')}>
            {tone === 'good' ? 'Хорошо' : tone === 'warning' ? 'Внимание' : 'Риск'}
          </span>
          {health.discipline === null ? <p className="mt-4 text-xs text-slate-400">Выставьте лимиты в разделе Бюджет</p> : <Gauge value={health.discipline} color={gaugeColor} />}
          {isExpanded ? <>
            <hr className="my-3 border-slate-100" />
            <div className="space-y-2.5">
              <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">Хронические нарушения</p>
              {health.discipline_violations.length === 0 ? <p className="text-xs text-slate-400">Нарушений не обнаружено</p> : health.discipline_violations.slice(0, 3).map((violation) => (
                <div key={violation.category_name} className="flex items-center justify-between gap-2">
                  <div className="min-w-0"><p className="truncate text-sm font-medium text-slate-900">{violation.category_name}</p><p className="text-xs text-slate-400">{violation.months_count} мес. подряд</p></div>
                  <span className="shrink-0 rounded-full bg-rose-100 px-2.5 py-0.5 text-xs font-medium text-rose-700">+{violation.overage_percent.toFixed(0)}%</span>
                </div>
              ))}
            </div>
            <div className="mt-3">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">Динамика</p>
              {health.discipline_history && health.discipline_history.length > 0 ? <div className="flex h-10 items-end gap-1.5">{health.discipline_history.slice(-3).map((item, index, array) => {
                const isLast = index === array.length - 1;
                const barColor = item.value >= 80 ? '#1D9E75' : item.value >= 60 ? '#EF9F27' : '#E24B4A';
                return <div key={item.month} className="flex flex-1 flex-col items-center gap-1"><span className="text-[10px] font-medium" style={{ color: barColor }}>{item.value.toFixed(0)}%</span><div className="w-full rounded-sm" style={{ height: `${Math.max((item.value / 100) * 32, 4)}px`, background: isLast ? barColor : `${barColor}80` }} /><span className="text-[9px] text-slate-300">{item.month}</span></div>;
              })}</div> : <div><div className="flex h-10 items-end gap-1.5">{[10, 18, 26].map((height, index) => <div key={index} className="flex flex-1 flex-col items-center gap-1"><span className="text-[10px] font-medium text-slate-300">--</span><div className="w-full rounded-sm bg-slate-200" style={{ height: `${height}px` }} /><span className="text-[9px] text-slate-300">--</span></div>)}</div><p className="mt-2 text-xs text-slate-400">Накапливается история...</p></div>}
            </div>
            <div className={cn('mt-3 rounded-lg px-3 py-2 text-xs', (health.discipline ?? 0) < 60 ? 'bg-rose-50 text-rose-700' : (health.discipline ?? 0) < 80 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700')}>{tip}</div>
          </> : null}
        </Card>
      </div>
    </div>
  );
}