import type { ImportRowStatus } from '@/types/import';
import { cn } from '@/lib/utils/cn';

const labels: Record<ImportRowStatus, string> = {
  ready: 'Готово',
  warning: 'Требует подтверждения',
  error: 'Ошибка',
  duplicate: 'Дубликат',
  skipped: 'Исключена',
  committed: 'Импортировано',
  parked: 'Отложено',
};

export function ImportStatusBadge({ status }: { status: ImportRowStatus }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium',
        status === 'ready' && 'bg-emerald-50 text-emerald-700',
        status === 'warning' && 'bg-amber-50 text-amber-700',
        status === 'error' && 'bg-rose-50 text-rose-700',
        status === 'duplicate' && 'bg-violet-50 text-violet-700',
        status === 'skipped' && 'bg-slate-100 text-slate-600',
        status === 'committed' && 'bg-sky-50 text-sky-700',
        status === 'parked' && 'bg-indigo-50 text-indigo-700',
      )}
    >
      {labels[status]}
    </span>
  );
}
