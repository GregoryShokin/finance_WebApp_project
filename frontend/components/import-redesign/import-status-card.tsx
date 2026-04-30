'use client';

/**
 * "Текущая выписка / Распределение операций" card.
 * Shows ready vs review counts + a thin progress bar.
 */

import { Check } from 'lucide-react';
import { Chip } from '@/components/ui/status-chip';
import { cn } from '@/lib/utils/cn';

export function ImportStatusCard({
  totalRows,
  readyRows,
  reviewRows,
  className,
}: {
  totalRows: number;
  readyRows: number;
  reviewRows: number;
  className?: string;
}) {
  const pct = totalRows === 0 ? 0 : Math.round((readyRows / totalRows) * 100);

  return (
    <section className={cn('surface-card p-5 lg:p-6', className)}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Текущая выписка</p>
          <h2 className="mt-1 font-serif text-2xl leading-tight text-ink">
            Распределение операций
          </h2>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Chip tone="green">
            <Check className="size-3" />
            {readyRows} готовы
          </Chip>
          {reviewRows > 0 ? (
            <Chip tone="amber">{reviewRows} требуют внимания</Chip>
          ) : null}
        </div>
      </div>

      <div className="mt-4 flex h-1.5 overflow-hidden rounded-pill bg-bg-surface2">
        <div
          className="h-full bg-accent-green transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </section>
  );
}
