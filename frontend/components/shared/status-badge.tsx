import { cn } from '@/lib/utils/cn';

export function StatusBadge({
  children,
  tone = 'neutral',
  className,
}: {
  children: React.ReactNode;
  tone?: 'neutral' | 'income' | 'expense' | 'warning' | 'info' | 'success';
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium',
        tone === 'neutral' && 'bg-slate-100 text-slate-700',
        tone === 'income' && 'bg-emerald-100 text-emerald-700',
        tone === 'expense' && 'bg-rose-100 text-rose-700',
        tone === 'warning' && 'bg-amber-100 text-amber-800',
        tone === 'info' && 'bg-sky-100 text-sky-800',
        tone === 'success' && 'bg-emerald-100 text-emerald-800',
        className,
      )}
    >
      {children}
    </span>
  );
}
