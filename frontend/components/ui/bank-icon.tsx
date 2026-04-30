'use client';

import { cn } from '@/lib/utils/cn';

type BankSpec = { c: string; dark: boolean; l: string };

// Hand-tuned brand colours for Russian banks the user actually imports from.
// Falls back to a neutral surface chip with the first letter of the bank name.
const BANK_MAP: Record<string, BankSpec> = {
  'Тинькофф':  { c: '#ffd900', dark: false, l: 'Т' },
  'Т-Банк':    { c: '#ffd900', dark: false, l: 'Т' },
  'Сбер':      { c: '#1ea84c', dark: true,  l: 'С' },
  'Сбербанк':  { c: '#1ea84c', dark: true,  l: 'С' },
  'Альфа':     { c: '#ef3124', dark: true,  l: 'А' },
  'Альфа-Банк':{ c: '#ef3124', dark: true,  l: 'А' },
  'ВТБ':       { c: '#00a3e0', dark: true,  l: 'В' },
  'Газпромбанк':{ c: '#1976d2', dark: true,  l: 'Г' },
  'Райффайзен':{ c: '#fff200', dark: false, l: 'Р' },
  'ЮMoney':    { c: '#8b3ffd', dark: true,  l: 'Ю' },
};

export function BankIcon({
  bank,
  size = 36,
  className,
}: {
  bank: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const fallback: BankSpec = {
    c: '#f5f3ee',
    dark: false,
    l: (bank ?? '?').charAt(0).toUpperCase() || '?',
  };
  const spec = (bank && BANK_MAP[bank]) || fallback;

  return (
    <div
      className={cn('grid shrink-0 place-items-center font-serif font-bold', className)}
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.25,
        background: spec.c,
        color: spec.dark ? '#fff' : '#000',
        fontSize: size * 0.4,
      }}
    >
      {spec.l}
    </div>
  );
}
