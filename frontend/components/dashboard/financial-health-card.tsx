'use client';

import type { ReactNode } from 'react';
import { Info } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';

export interface FinancialHealthCardProps {
  title: string;
  value: string | number;
  zone: 'good' | 'warning' | 'danger';
  isExpanded: boolean;
  onToggle: () => void;
  collapsedContent?: ReactNode;
  expandedContent: ReactNode;
}

const zoneStyles: Record<FinancialHealthCardProps['zone'], { badge: string; label: string; value: string }> = {
  good: {
    badge: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    label: 'Хорошо',
    value: 'text-emerald-600',
  },
  warning: {
    badge: 'bg-amber-100 text-amber-700 border-amber-200',
    label: 'Внимание',
    value: 'text-amber-600',
  },
  danger: {
    badge: 'bg-rose-100 text-rose-700 border-rose-200',
    label: 'Риск',
    value: 'text-rose-600',
  },
};

export function FinancialHealthCard({
  title,
  value,
  zone,
  isExpanded,
  onToggle,
  collapsedContent,
  expandedContent,
}: FinancialHealthCardProps) {
  const styles = zoneStyles[zone];

  return (
    <Card className="overflow-hidden border border-white/60 p-5 shadow-soft lg:p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-500">{title}</p>
          <div className={cn('mt-3 text-2xl font-semibold tabular-nums lg:text-3xl', styles.value)}>{value}</div>
          <span className={cn('mt-3 inline-flex rounded-full border px-2.5 py-1 text-xs font-medium', styles.badge)}>
            {styles.label}
          </span>
          {collapsedContent ? <div>{collapsedContent}</div> : null}
        </div>
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={isExpanded}
          aria-label={`Показать детали: ${title}`}
          className="flex size-9 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-500 transition hover:border-slate-300 hover:text-slate-700"
        >
          <Info className="size-4" />
        </button>
      </div>

      <div
        className={cn('card-expanded-content', isExpanded && 'open', isExpanded && 'mt-4')}
        style={{
          overflow: 'hidden',
          maxHeight: isExpanded ? '600px' : '0',
          opacity: isExpanded ? 1 : 0,
          transition: 'max-height 400ms cubic-bezier(0.34, 1.56, 0.64, 1), opacity 300ms ease',
        }}
      >
        <div className="border-t border-slate-100 pt-4">{expandedContent}</div>
      </div>
    </Card>
  );
}