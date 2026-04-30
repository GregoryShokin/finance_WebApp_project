'use client';

import { type ReactNode } from 'react';
import { cn } from '@/lib/utils/cn';

export type ChipTone = 'green' | 'amber' | 'red' | 'blue' | 'violet' | 'line';

const TONE: Record<ChipTone, string> = {
  green: 'chip-green',
  amber: 'chip-amber',
  red: 'chip-red',
  blue: 'chip-blue',
  violet: 'chip-violet',
  line: 'chip-line',
};

export function Chip({
  tone = 'line',
  children,
  className,
}: {
  tone?: ChipTone;
  children: ReactNode;
  className?: string;
}) {
  return <span className={cn('chip', TONE[tone], className)}>{children}</span>;
}

export type DotTone = Exclude<ChipTone, 'line'>;

const DOT: Record<DotTone, string> = {
  green: 'dot-green',
  amber: 'dot-amber',
  red: 'dot-red',
  blue: 'dot-blue',
  violet: 'dot-violet',
};

export function Dot({ tone = 'amber', className }: { tone?: DotTone; className?: string }) {
  return <span className={cn('dot', DOT[tone], className)} />;
}
