'use client';

import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils/cn';

export function Gauge({ value, tone }: { value: number; tone: 'good' | 'warning' | 'danger' }) {
  const radius = 54;
  const circumference = Math.PI * radius;
  const normalizedValue = Math.max(0, Math.min(100, value));
  const dashOffset = circumference - (normalizedValue / 100) * circumference;
  const [animatedOffset, setAnimatedOffset] = useState(circumference);

  useEffect(() => {
    const id = window.setTimeout(() => setAnimatedOffset(dashOffset), 60);
    return () => window.clearTimeout(id);
  }, [dashOffset]);

  const stroke = useMemo(() => {
    if (tone === 'danger') return '#ef4444';
    if (tone === 'warning') return '#f59e0b';
    return '#10b981';
  }, [tone]);

  return (
    <div className="relative flex h-36 w-full items-center justify-center">
      <svg viewBox="0 0 140 90" className="h-full w-full overflow-visible">
        <path d="M 16 70 A 54 54 0 0 1 124 70" fill="none" stroke="#e2e8f0" strokeWidth="12" strokeLinecap="round" />
        <path
          d="M 16 70 A 54 54 0 0 1 124 70"
          fill="none"
          stroke={stroke}
          strokeWidth="12"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={animatedOffset}
          className="transition-[stroke-dashoffset] duration-[800ms] ease-in-out"
        />
      </svg>
      <div className="absolute top-12 flex flex-col items-center">
        <span className={cn('text-3xl font-semibold tabular-nums', tone === 'danger' ? 'text-rose-600' : tone === 'warning' ? 'text-amber-600' : 'text-emerald-600')}>
          {value.toFixed(0)}%
        </span>
        <span className="text-xs text-slate-400">текущий уровень</span>
      </div>
    </div>
  );
}