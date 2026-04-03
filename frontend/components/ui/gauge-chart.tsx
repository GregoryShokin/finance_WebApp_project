'use client';

import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils/cn';

const ARC_LENGTH = 157;

export function GaugeChart({
  value,
  tone,
  label,
  clampToHundred = true,
}: {
  value: number;
  tone: string;
  label?: string;
  clampToHundred?: boolean;
}) {
  const normalized = clampToHundred ? Math.min(Math.max(value, 0), 100) : Math.max(value, 0);
  const targetOffset = ARC_LENGTH - (normalized / 100) * ARC_LENGTH;
  const [dashOffset, setDashOffset] = useState(ARC_LENGTH);

  useEffect(() => {
    setDashOffset(targetOffset);
  }, [targetOffset]);

  return (
    <div className="mt-4">
      <svg viewBox="0 0 120 70" className="h-[72px] w-full">
        <path
          d="M10,60 A50,50 0 0,1 110,60"
          fill="none"
          stroke="#F1EFE8"
          strokeWidth="10"
          strokeLinecap="round"
        />
        <path
          d="M10,60 A50,50 0 0,1 110,60"
          fill="none"
          stroke={tone}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={ARC_LENGTH}
          strokeDashoffset={dashOffset}
          style={{ transition: 'stroke-dashoffset 800ms ease' }}
        />
        <text x="60" y="58" textAnchor="middle" className={cn('fill-slate-700 text-[12px] font-semibold')}>
          {value.toFixed(1)}%
        </text>
      </svg>
      {label ? <p className="mt-1 text-center text-[10px] text-[#B4B2A9]">{label}</p> : null}
    </div>
  );
}
