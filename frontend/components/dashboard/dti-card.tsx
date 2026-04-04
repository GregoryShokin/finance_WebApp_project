'use client';

import { useEffect, useRef, useState } from 'react';

import { dtiTone } from '@/components/dashboard/card-tones';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { FinancialHealth } from '@/types/financial-health';

const SCALE = 1.8;
const ARC_LENGTH = 157;

function getGaugeColor(dti: number): string {
  if (dti > 60) return '#A32D2D';
  if (dti > 40) return '#E24B4A';
  if (dti >= 30) return '#EF9F27';
  return '#1D9E75';
}

function getTip(dti: number): string {
  if (dti > 60) return 'Критическая нагрузка - приоритет на погашение крупнейшего кредита';
  if (dti > 40) return 'Нагрузка высокая - старайся не брать новые кредиты';
  if (dti > 30) return 'Нагрузка допустимая - следи чтобы не росла';
  return 'Нагрузка в норме - хороший показатель';
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
        <path d="M10,62 A50,50 0 0,1 110,62" fill="none" stroke="#F1EFE8" strokeWidth="14" strokeLinecap="round" />
        <path d="M10,62 A50,50 0 0,1 110,62" fill="none" stroke={color} strokeWidth="14" strokeLinecap="round" strokeDasharray={ARC_LENGTH} strokeDashoffset={dashOffset} style={{ transition: 'stroke-dashoffset 800ms ease' }} />
        <text x="60" y="56" textAnchor="middle" className="fill-slate-800 text-[16px] font-semibold">{value.toFixed(1)}%</text>
      </svg>
      <p className="mt-1 text-center text-[10px] text-[#B4B2A9]">ежемесячная нагрузка</p>
    </div>
  );
}

export function DTICard({ health, isExpanded, onToggle }: { health: FinancialHealth; isExpanded: boolean; onToggle: () => void }) {
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
      if (!wrapperRef.current?.contains(event.target as Node)) onToggle();
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isExpanded, onToggle]);

  const tone = dtiTone(health.dti_zone);
  const gaugeColor = getGaugeColor(health.dti);
  const tip = getTip(health.dti);

  return (
    <div ref={wrapperRef} className="relative h-full overflow-visible" style={{ height: collapsedHeight > 0 ? `${collapsedHeight}px` : 'auto' }}>
      {isExpanded ? <button type="button" aria-label="Закрыть" onClick={onToggle} className="fixed inset-0 z-40 bg-black/10" /> : null}
      <div ref={cardRef}>
        <Card className="relative overflow-visible p-5" style={{ position: isExpanded ? 'absolute' : 'relative', top: 0, left: 0, right: 0, transform: isExpanded ? `scale(${SCALE})` : 'scale(1)', transformOrigin: 'center center', transition: 'transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)', zIndex: isExpanded ? 50 : 1, overflow: 'visible' }}>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Кредитная нагрузка</p>
          <button type="button" onClick={onToggle} className="absolute right-3 top-3 flex size-[22px] items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-[11px] font-medium text-slate-500 transition hover:border-slate-800 hover:bg-slate-800 hover:text-white" aria-label="Подробнее" aria-expanded={isExpanded}>i</button>
          <span className={cn('mt-2 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium', tone === 'good' ? 'bg-emerald-100 text-emerald-700' : tone === 'warning' ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700')}>
            {tone === 'good' ? 'Хорошо' : tone === 'warning' ? 'Внимание' : 'Риск'}
          </span>
          <Gauge value={health.dti} color={gaugeColor} />
          {isExpanded ? <>
            <hr className="my-3 border-slate-100" />
            <div className="space-y-2.5">
              <div className="flex items-center justify-between"><span className="text-sm text-slate-500">Средний доход</span><span className="text-sm font-medium text-slate-900">{formatMoney(health.dti_income)} / мес</span></div>
              <div className="mt-2 flex items-center justify-between"><span className="text-sm text-slate-500">Сумма платежей</span><span className="text-sm font-medium text-rose-600">{formatMoney(health.dti_total_payments)} / мес</span></div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {[{ label: '<30% - норма', bg: 'bg-emerald-100', text: 'text-emerald-700' }, { label: '30-40% - допустимо', bg: 'bg-amber-100', text: 'text-amber-700' }, { label: '>40% - опасно', bg: 'bg-rose-100', text: 'text-rose-700' }, { label: '>60% - критично', bg: 'bg-red-200', text: 'text-red-800' }].map((zone) => <span key={zone.label} className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${zone.bg} ${zone.text}`}>{zone.label}</span>)}
            </div>
            <div className={cn('mt-3 rounded-lg px-3 py-2 text-xs', health.dti > 40 ? 'bg-rose-50 text-rose-700' : health.dti > 30 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700')}>{tip}</div>
          </> : null}
        </Card>
      </div>
    </div>
  );
}