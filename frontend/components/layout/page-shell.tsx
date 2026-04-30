import { ReactNode } from 'react';
import { cn } from '@/lib/utils/cn';

export function PageShell({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('space-y-5 lg:space-y-6', className)}>
      <div className="flex flex-col gap-4 surface-panel p-5 lg:flex-row lg:items-start lg:justify-between lg:p-6">
        <div className="max-w-3xl">
          <p className="eyebrow mb-1.5">FinanceApp</p>
          <h2 className="font-serif text-3xl leading-tight text-ink lg:text-4xl">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-ink-2">{description}</p>
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      <div className="page-grid">{children}</div>
    </section>
  );
}
