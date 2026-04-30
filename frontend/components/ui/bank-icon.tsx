'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils/cn';

type BankSpec = { c: string; dark: boolean; l: string };

// Hand-tuned brand colours used for the fallback (coloured-letter) chip when
// a bank logo file is missing or fails to load. Falls back to a neutral
// surface chip with the first letter of the bank name.
const BANK_COLOR_BY_NAME: Record<string, BankSpec> = {
  'Тинькофф':   { c: '#ffd900', dark: false, l: 'Т' },
  'Т-Банк':     { c: '#ffd900', dark: false, l: 'Т' },
  'Сбер':       { c: '#1ea84c', dark: true,  l: 'С' },
  'Сбербанк':   { c: '#1ea84c', dark: true,  l: 'С' },
  'Альфа':      { c: '#ef3124', dark: true,  l: 'А' },
  'Альфа-Банк': { c: '#ef3124', dark: true,  l: 'А' },
  'ВТБ':        { c: '#00a3e0', dark: true,  l: 'В' },
  'Газпромбанк':{ c: '#1976d2', dark: true,  l: 'Г' },
  'Райффайзен': { c: '#fff200', dark: false, l: 'Р' },
  'ЮMoney':     { c: '#8b3ffd', dark: true,  l: 'Ю' },
};

// bank.name → bank.code mapping for the 30 banks seeded in alembic
// migration 0045. Lets callers pass the human name (current convention)
// while we resolve to the code-based logo file path.
const NAME_TO_CODE: Record<string, string> = {
  'Сбербанк':           'sber',
  'Сбер':               'sber',
  'Т-Банк':             'tbank',
  'Тинькофф':           'tbank',
  'Альфа-Банк':         'alfa',
  'Альфа':              'alfa',
  'ВТБ':                'vtb',
  'Газпромбанк':        'gazprombank',
  'Яндекс Банк':        'yandex',
  'Озон Банк':          'ozon',
  'Райффайзенбанк':     'raiffeisen',
  'Райффайзен':         'raiffeisen',
  'Росбанк':            'rosbank',
  'Промсвязьбанк':      'psb',
  'Совкомбанк':         'sovcombank',
  'Русский Стандарт':   'russkiy_standart',
  'МТС Банк':           'mts',
  'Почта Банк':         'pochta',
  'Открытие':           'otkrytie',
  'Хоум Банк':          'home_credit',
  'ДОМ.РФ':             'domrf',
  'РНКБ':               'rnkb',
  'БКС Банк':           'bks',
  'Ак Барс':            'akbars',
  'Банк Санкт-Петербург':'bspb',
  'Уралсиб':            'uralsib',
  'СМП Банк':           'smp',
  'ВБРР':               'vbrr',
  'Абсолют Банк':       'absolut',
  'Авангард':           'avangard',
  'Экспобанк':          'expo',
  'Банк ДОМ.РФ':        'domrf_bank',
  'Ренессанс Кредит':   'renaissance',
  'Банк Зенит':         'zenit',
};

function logoSrcFor(code: string | null | undefined): string | null {
  if (!code) return null;
  return `/bank-logos/${code}.png`;
}

function resolveCode(props: { code?: string | null; bank?: string | null }): string | null {
  if (props.code) return props.code;
  if (props.bank && NAME_TO_CODE[props.bank]) return NAME_TO_CODE[props.bank];
  return null;
}

export function BankIcon({
  bank,
  code,
  size = 36,
  className,
}: {
  /** Bank display name (legacy callers pass this). */
  bank?: string | null;
  /** Bank code (preferred — points directly at the logo file). */
  code?: string | null;
  size?: number;
  className?: string;
}) {
  const resolvedCode = resolveCode({ code, bank });
  const src = logoSrcFor(resolvedCode);
  const [errored, setErrored] = useState(false);

  // Render the actual logo when we have one and it hasn't failed to load.
  if (src && !errored) {
    return (
      <div
        className={cn('grid shrink-0 place-items-center overflow-hidden bg-white', className)}
        style={{
          width: size,
          height: size,
          borderRadius: size * 0.25,
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={bank ?? resolvedCode ?? 'bank logo'}
          width={size}
          height={size}
          loading="lazy"
          onError={() => setErrored(true)}
          style={{ objectFit: 'contain', width: '100%', height: '100%' }}
        />
      </div>
    );
  }

  // Fallback: coloured letter chip.
  const fallback: BankSpec = {
    c: '#f5f3ee',
    dark: false,
    l: (bank ?? '?').charAt(0).toUpperCase() || '?',
  };
  const spec = (bank && BANK_COLOR_BY_NAME[bank]) || fallback;

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
