'use client';

import { type ComponentType, type SVGProps } from 'react';
import { Check, Trash2, Clock4 } from 'lucide-react';
import { cn } from '@/lib/utils/cn';

type Kind = 'apply' | 'snooze' | 'excl';

type Cfg = {
  bg: string;
  bgActive: string;
  fg: string;
  fgActive: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  title: string;
};

const CFG: Record<Kind, Cfg> = {
  apply: {
    bg: 'bg-[#dff0e2]',
    bgActive: 'bg-[#1e8a4f] border-[#1e8a4f]',
    fg: 'text-[#0d6135]',
    fgActive: 'text-white',
    Icon: Check,
    title: 'Подтвердить',
  },
  snooze: {
    bg: 'bg-[#fdf2d4]',
    bgActive: 'bg-[#d49b1a] border-[#d49b1a]',
    fg: 'text-[#8a5a00]',
    fgActive: 'text-white',
    Icon: Clock4,
    title: 'Отложить на потом',
  },
  excl: {
    bg: 'bg-[#fdecea]',
    bgActive: 'bg-[#e54033] border-[#e54033]',
    fg: 'text-[#c92a1c]',
    fgActive: 'text-white',
    Icon: Trash2,
    title: 'Исключить из импорта',
  },
};

export function TrafficBtn({
  kind,
  active,
  onClick,
  title,
  size = 'md',
}: {
  kind: Kind;
  active?: boolean;
  onClick?: () => void;
  title?: string;
  size?: 'md' | 'lg';
}) {
  const cfg = CFG[kind];
  const dim = size === 'lg' ? 'size-12 rounded-full' : 'size-8 rounded-[9px]';

  return (
    <button
      type="button"
      onClick={onClick}
      title={title || cfg.title}
      className={cn(
        'grid place-items-center border transition active:translate-y-px',
        dim,
        active
          ? `${cfg.bgActive} ${cfg.fgActive}`
          : `${cfg.bg} ${cfg.fg} border-transparent hover:-translate-y-px`,
      )}
    >
      <cfg.Icon className={size === 'lg' ? 'size-[18px]' : 'size-3.5'} />
    </button>
  );
}
