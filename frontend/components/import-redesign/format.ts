/**
 * Money + date formatters reused across the warm-design import screens.
 */

const ABS_RUB = new Intl.NumberFormat('ru-RU', {
  style: 'decimal',
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});

export function fmtRub(amount: number | string | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  const abs = Math.abs(n);
  const fmt = ABS_RUB.format(abs);
  if (n === 0) return `${fmt} ₽`;
  const sign = n < 0 ? '−' : '+';
  return `${sign}${fmt} ₽`;
}

/**
 * Render an import-row amount with the sign derived from `direction`.
 * The bank-statement parser stores amounts as positive magnitudes, so the
 * naïve "amount > 0 ⇒ +" logic flips every expense into income.
 * Always pair amount with its row.normalized_data.direction.
 */
export function fmtRubSigned(
  amount: number | string | null | undefined,
  direction: 'income' | 'expense' | string | null | undefined,
): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  const abs = Math.abs(n);
  const fmt = ABS_RUB.format(abs);
  if (abs === 0) return `${fmt} ₽`;
  const sign = direction === 'income' ? '+' : '−';
  return `${sign}${fmt} ₽`;
}

export function fmtRubAbs(amount: number | string | null | undefined): string {
  if (amount === null || amount === undefined || amount === '') return '—';
  const n = typeof amount === 'string' ? Number(amount) : amount;
  if (!Number.isFinite(n)) return String(amount);
  return `${ABS_RUB.format(Math.abs(n))} ₽`;
}

const DATE_FMT = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });

export function fmtDateShort(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return DATE_FMT.format(d);
}

/** дд.мм.гггг | чч:мм */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const datePart = DATE_FMT.format(d);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${datePart} | ${hh}:${mm}`;
}

export function fmtDateLong(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(d);
}

export function fmtPeriod(fromIso: string | null, toIso: string | null): string {
  if (!fromIso || !toIso) return '';
  const from = new Date(fromIso);
  const to = new Date(toIso);
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return '';
  const sameMonth = from.getMonth() === to.getMonth() && from.getFullYear() === to.getFullYear();
  if (sameMonth) {
    return new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric' }).format(from);
  }
  const f = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit' }).format(from);
  const t = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(to);
  return `${f} — ${t}`;
}
