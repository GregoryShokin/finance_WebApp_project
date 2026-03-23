import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';

export function MoneyAmount({
  value,
  currency = 'RUB',
  tone = 'default',
  showSign = false,
  className,
}: {
  value: number | string;
  currency?: string;
  tone?: 'default' | 'income' | 'expense';
  showSign?: boolean;
  className?: string;
}) {
  const numeric = typeof value === 'string' ? Number(value) : value;
  const safe = Number.isFinite(numeric) ? numeric : 0;
  const absFormatted = formatMoney(Math.abs(safe), currency);
  const signed = showSign && safe > 0 ? `+${absFormatted}` : showSign && safe < 0 ? `-${absFormatted}` : formatMoney(safe, currency);

  return (
    <span
      className={cn(
        'font-semibold tabular-nums',
        tone === 'default' && 'text-slate-950',
        tone === 'income' && 'text-emerald-600',
        tone === 'expense' && 'text-rose-600',
        className,
      )}
    >
      {signed}
    </span>
  );
}
