export function formatMoney(value: number | string, currency = 'RUB') {
  const amount = typeof value === 'string' ? Number(value) : value;
  const safeValue = Number.isFinite(amount) ? amount : 0;

  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(safeValue);
}

export function formatDateTime(value: string | Date) {
  const date = value instanceof Date ? value : new Date(value);
  const datePart = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date);
  const timePart = new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
  return `${datePart} | ${timePart}`;
}
