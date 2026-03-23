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
    <section className={cn('space-y-6 lg:space-y-7', className)}>
      <div className="flex flex-col gap-4 rounded-3xl border border-white/60 bg-white/70 p-5 shadow-soft backdrop-blur lg:flex-row lg:items-start lg:justify-between lg:p-6">
        <div className="max-w-3xl">
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">FinanceApp</p>
          <h2 className="text-2xl font-semibold text-slate-950 lg:text-3xl">{title}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500 lg:text-[15px]">{description}</p>
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
      <div className="page-grid">{children}</div>
    </section>
  );
}
