'use client';

import { useMemo, useState } from 'react';
import { TrendingDown, TrendingUp, Minus } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { useCapitalHistory } from '@/hooks/use-capital-history';
import type { CapitalHistoryPoint } from '@/types/financial-health';

const SECTION_CARD =
  'rounded-3xl border border-white/60 bg-white/85 p-5 shadow-soft backdrop-blur lg:p-6';

const COLOR_LIQUID = '#1D9E75';
const COLOR_NET = '#6B5CE7';
const COLOR_DEBT = '#E24B4A';
const COLOR_GRID = '#E2E8F0';
const COLOR_AXIS_LABEL = '#94A3B8';

type Delta = {
  absolute: number;
  percent: number | null;
};

function computeDelta(first: number, last: number): Delta {
  const absolute = last - first;
  if (first === 0) {
    return { absolute, percent: null };
  }
  return { absolute, percent: (absolute / Math.abs(first)) * 100 };
}

function DeltaBadge({ delta, invert = false }: { delta: Delta; invert?: boolean }) {
  const neutral = delta.absolute === 0;
  const up = delta.absolute > 0;
  const good = invert ? !up && !neutral : up && !neutral;
  const Icon = neutral ? Minus : up ? TrendingUp : TrendingDown;
  const color = neutral
    ? 'text-slate-500 bg-slate-100'
    : good
    ? 'text-emerald-700 bg-emerald-50'
    : 'text-rose-700 bg-rose-50';
  const sign = delta.absolute > 0 ? '+' : '';
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', color)}>
      <Icon className="size-3" />
      {sign}
      {formatMoney(delta.absolute)}
      {delta.percent !== null ? ` · ${sign}${delta.percent.toFixed(1)}%` : ''}
    </span>
  );
}

type SeriesKey = 'net_capital' | 'liquid_capital' | 'debt';

type HoverState = { index: number; x: number; y: number } | null;

function TrendSvg({
  points,
  hover,
  setHover,
}: {
  points: CapitalHistoryPoint[];
  hover: HoverState;
  setHover: (state: HoverState) => void;
}) {
  const width = 720;
  const height = 260;
  const padLeft = 56;
  const padRight = 16;
  const padTop = 18;
  const padBottom = 32;
  const chartWidth = width - padLeft - padRight;
  const chartHeight = height - padTop - padBottom;

  const { minY, maxY } = useMemo(() => {
    let min = 0;
    let max = 0;
    for (const p of points) {
      max = Math.max(max, p.net_capital, p.liquid_capital);
      min = Math.min(min, p.net_capital, p.liquid_capital, -p.total_debt);
    }
    if (max === min) {
      max = max + 1;
    }
    return { minY: min, maxY: max };
  }, [points]);

  const yFor = (v: number) =>
    padTop + chartHeight - ((v - minY) / (maxY - minY)) * chartHeight;
  const xFor = (index: number) => {
    if (points.length <= 1) return padLeft + chartWidth / 2;
    return padLeft + (index / (points.length - 1)) * chartWidth;
  };

  const buildPath = (key: SeriesKey) =>
    points
      .map((p, i) => {
        const value = key === 'debt' ? -p.total_debt : (p[key] as number);
        const x = xFor(i);
        const y = yFor(value);
        return `${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(' ');

  const netPath = buildPath('net_capital');
  const liquidPath = buildPath('liquid_capital');

  const yZero = yFor(0);

  const ticks = useMemo(() => {
    const range = maxY - minY;
    const step = niceStep(range / 4);
    const start = Math.ceil(minY / step) * step;
    const arr: number[] = [];
    for (let v = start; v <= maxY; v += step) {
      arr.push(v);
      if (arr.length > 8) break;
    }
    return arr;
  }, [minY, maxY]);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full overflow-visible">
      {ticks.map((t) => {
        const y = yFor(t);
        return (
          <g key={t}>
            <line x1={padLeft} y1={y} x2={width - padRight} y2={y} stroke={COLOR_GRID} strokeDasharray={t === 0 ? '4 4' : undefined} />
            <text x={padLeft - 8} y={y + 3} fontSize="10" textAnchor="end" fill={COLOR_AXIS_LABEL}>
              {formatCompact(t)}
            </text>
          </g>
        );
      })}

      {minY < 0 && (
        <line x1={padLeft} y1={yZero} x2={width - padRight} y2={yZero} stroke="#CBD5E1" strokeDasharray="2 3" />
      )}

      {points.map((p, i) => {
        if (p.total_debt <= 0) return null;
        const x = xFor(i);
        const yTop = yFor(0);
        const yBot = yFor(-p.total_debt);
        const bw = Math.min(22, (chartWidth / Math.max(points.length, 1)) * 0.35);
        return (
          <rect
            key={`debt-${p.month}`}
            x={x - bw / 2}
            y={yTop}
            width={bw}
            height={Math.max(yBot - yTop, 1)}
            rx="3"
            fill={COLOR_DEBT}
            opacity="0.25"
          />
        );
      })}

      <path d={liquidPath} fill="none" stroke={COLOR_LIQUID} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d={netPath} fill="none" stroke={COLOR_NET} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />

      {points.map((p, i) => {
        const x = xFor(i);
        return (
          <g key={`dots-${p.month}`}>
            <circle cx={x} cy={yFor(p.liquid_capital)} r="3.5" fill={COLOR_LIQUID} />
            <circle cx={x} cy={yFor(p.net_capital)} r="3.5" fill={COLOR_NET} />
          </g>
        );
      })}

      {points.map((p, i) => {
        const x = xFor(i);
        return (
          <text key={`xlbl-${p.month}`} x={x} y={height - 10} fontSize="11" textAnchor="middle" fill="#64748B">
            {p.label}
          </text>
        );
      })}

      {points.map((p, i) => {
        const x = xFor(i);
        const bw = chartWidth / Math.max(points.length - 1, 1);
        return (
          <rect
            key={`hit-${p.month}`}
            x={x - bw / 2}
            y={padTop}
            width={bw}
            height={chartHeight}
            fill="transparent"
            onMouseEnter={() => setHover({ index: i, x, y: yFor(p.net_capital) })}
            onMouseLeave={() => setHover(null)}
          />
        );
      })}

      {hover && (
        <line
          x1={xFor(hover.index)}
          y1={padTop}
          x2={xFor(hover.index)}
          y2={padTop + chartHeight}
          stroke="#94A3B8"
          strokeDasharray="3 3"
        />
      )}
    </svg>
  );
}

function niceStep(raw: number): number {
  if (raw <= 0) return 1;
  const exp = Math.floor(Math.log10(raw));
  const base = Math.pow(10, exp);
  const mult = raw / base;
  if (mult < 1.5) return base;
  if (mult < 3) return 2 * base;
  if (mult < 7) return 5 * base;
  return 10 * base;
}

function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`;
  return value.toFixed(0);
}

export function CapitalTrendChart() {
  const { data, isLoading, error } = useCapitalHistory(6);
  const [hover, setHover] = useState<HoverState>(null);

  if (isLoading) {
    return (
      <Card className={SECTION_CARD}>
        <div className="h-[300px] animate-pulse rounded-2xl bg-slate-100/60" />
      </Card>
    );
  }

  if (error || !data || data.length === 0) {
    return (
      <Card className={SECTION_CARD}>
        <h3 className="text-lg font-semibold text-slate-950">Динамика капитала</h3>
        <p className="mt-2 text-sm text-slate-500">
          Недостаточно данных для построения динамики. Внесите транзакции за несколько месяцев.
        </p>
      </Card>
    );
  }

  const first = data[0];
  const last = data[data.length - 1];
  const netDelta = computeDelta(first.net_capital, last.net_capital);
  const liquidDelta = computeDelta(first.liquid_capital, last.liquid_capital);
  const debtDelta = computeDelta(first.total_debt, last.total_debt);

  const hovered = hover ? data[hover.index] : null;

  return (
    <Card className={cn(SECTION_CARD)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">Динамика капитала</h3>
          <p className="mt-1 text-sm text-slate-500">
            Как менялся ликвидный и чистый капитал за последние 6 месяцев.
          </p>
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl bg-slate-50/80 p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: COLOR_LIQUID }} />
            Ликвидный капитал
          </div>
          <p className="mt-2 text-xl font-semibold text-slate-950">{formatMoney(last.liquid_capital)}</p>
          <div className="mt-1">
            <DeltaBadge delta={liquidDelta} />
          </div>
        </div>
        <div className="rounded-2xl bg-slate-50/80 p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: COLOR_NET }} />
            Чистый капитал
          </div>
          <p className="mt-2 text-xl font-semibold text-slate-950">{formatMoney(last.net_capital)}</p>
          <div className="mt-1">
            <DeltaBadge delta={netDelta} />
          </div>
        </div>
        <div className="rounded-2xl bg-slate-50/80 p-4">
          <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
            <span className="size-2.5 rounded-full" style={{ backgroundColor: COLOR_DEBT, opacity: 0.5 }} />
            Долги
          </div>
          <p className="mt-2 text-xl font-semibold text-slate-950">{formatMoney(last.total_debt)}</p>
          <div className="mt-1">
            <DeltaBadge delta={debtDelta} invert />
          </div>
        </div>
      </div>

      <div className="relative mt-5">
        <TrendSvg points={data} hover={hover} setHover={setHover} />

        {hovered && (
          <div className="pointer-events-none absolute right-2 top-2 min-w-[180px] rounded-xl border border-slate-200 bg-white/95 p-3 shadow-lg">
            <p className="text-xs font-semibold text-slate-900">{hovered.label}</p>
            <div className="mt-2 space-y-1 text-xs text-slate-600">
              <div className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ backgroundColor: COLOR_NET }} />
                  Чистый
                </span>
                <span className="font-medium text-slate-900">{formatMoney(hovered.net_capital)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ backgroundColor: COLOR_LIQUID }} />
                  Ликвидный
                </span>
                <span className="font-medium text-slate-900">{formatMoney(hovered.liquid_capital)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full" style={{ backgroundColor: COLOR_DEBT, opacity: 0.5 }} />
                  Долг
                </span>
                <span className="font-medium text-slate-900">{formatMoney(hovered.total_debt)}</span>
              </div>
              {hovered.real_assets > 0 && (
                <div className="flex items-center justify-between gap-3 border-t border-slate-100 pt-1 text-[11px] text-slate-500">
                  <span>в т.ч. активы</span>
                  <span>{formatMoney(hovered.real_assets)}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <p className="mt-3 text-[11px] leading-5 text-slate-400">
        Недвижимость и активы учтены по текущей оценке — если вы меняли её, старые месяцы могут быть неточны.
      </p>
    </Card>
  );
}
