'use client';

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { getBudgetProgress } from '@/lib/api/budget';
import { useExpandableCard } from '@/hooks/use-expandable-card';
import type { BudgetProgress } from '@/types/budget';

function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-01`;
}

type GroupTotals = {
  planned: number;
  spent: number;
  pct: number;
};

function sumGroup(items: BudgetProgress[], priority: string): GroupTotals {
  const filtered = items.filter((i) => i.category_priority === priority);
  const planned = filtered.reduce((sum, item) => sum + Number(item.planned_amount), 0);
  const spent = filtered.reduce((sum, item) => sum + Number(item.spent_amount), 0);
  const pct = planned > 0 ? (spent / planned) * 100 : 0;
  return { planned, spent, pct };
}

function getMonthElapsed() {
  const now = new Date();
  const total = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const elapsed = now.getDate();
  return { elapsed, total, pct: Math.min(100, (elapsed / total) * 100) };
}

// Цвет бара зависит только от процента выполнения плана, без оглядки на темп месяца
function barColor(spentPct: number): string {
  if (spentPct === 0) return 'bg-slate-200';
  if (spentPct < 80) return 'bg-emerald-500';   // ещё есть запас
  if (spentPct < 100) return 'bg-slate-500';    // почти на пределе
  if (spentPct < 120) return 'bg-amber-500';    // лёгкое превышение
  return 'bg-rose-500';                          // явный перерасход
}

type StatusResult = {
  text: string;
  tone: string;
};

function computeStatus(essentialPct: number, secondaryPct: number, monthPct: number, hasAnyPlan: boolean): StatusResult {
  if (!hasAnyPlan) {
    return { text: 'Бюджет не задан', tone: 'text-slate-400' };
  }

  // Берём худшую из двух групп — именно она задаёт тон месяца
  const worst = Math.max(essentialPct, secondaryPct);
  const delta = worst - monthPct;

  if (delta <= -5) {
    return { text: `Опережаешь план на ${Math.round(Math.abs(delta))}%`, tone: 'text-emerald-600' };
  }
  if (delta <= 10) {
    return { text: 'Идёшь по графику', tone: 'text-slate-700' };
  }
  if (delta <= 25) {
    return { text: `Отстаёшь на ${Math.round(delta)}%`, tone: 'text-amber-600' };
  }
  return { text: `Перерасход на ${Math.round(delta)}%`, tone: 'text-rose-600' };
}

type Props = {
  isLoading?: boolean;
};

export function BudgetPaceWidget({ isLoading: externalLoading = false }: Props) {
  const monthKey = useMemo(currentMonthKey, []);
  const budgetQuery = useQuery({
    queryKey: ['budget', monthKey],
    queryFn: () => getBudgetProgress(monthKey),
    staleTime: 1000 * 60 * 2,
  });

  const isLoading = externalLoading || budgetQuery.isLoading;
  const items = budgetQuery.data ?? [];

  const monthInfo = useMemo(getMonthElapsed, []);
  const essential = useMemo(() => sumGroup(items, 'expense_essential'), [items]);
  const secondary = useMemo(() => sumGroup(items, 'expense_secondary'), [items]);

  const hasAnyPlan = essential.planned > 0 || secondary.planned > 0;
  const status = useMemo(
    () => computeStatus(essential.pct, secondary.pct, monthInfo.pct, hasAnyPlan),
    [essential.pct, secondary.pct, monthInfo.pct, hasAnyPlan],
  );

  const {
    wrapperRef,
    cardRef,
    isExpanded,
    wrapperStyle,
    cardStyle,
    backdrop,
    toggleButton,
  } = useExpandableCard({ id: 'budget-pace-widget', expandHeight: 360 });

  function renderBar(label: string, pct: number, barCls: string, subtitle?: string) {
    return (
      <div>
        <div className="mb-1 flex items-center justify-between text-xs">
          <span className="text-slate-500">{label}</span>
          <span className="font-medium text-slate-700 tabular-nums">{Math.round(pct)}%</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={cn('h-full rounded-full transition-all duration-500', barCls)}
            style={{ width: `${Math.min(100, pct)}%` }}
          />
        </div>
        {subtitle ? <p className="mt-1 text-[11px] text-slate-400">{subtitle}</p> : null}
      </div>
    );
  }

  function renderContent() {
    if (isLoading) {
      return (
        <>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Темп расходов</p>
          <div className="mt-3 space-y-3">
            <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
            <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
            <div className="h-1.5 w-full animate-pulse rounded-full bg-slate-100" />
          </div>
        </>
      );
    }

    return (
      <>
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Темп расходов</p>

        {toggleButton}

        {/* В раскрытом виде — статус «Опережаешь план на N%» и пояснение по дням */}
        {isExpanded ? (
          <>
            <p className={cn('mt-2 text-lg font-semibold leading-snug', status.tone)}>{status.text}</p>
            <p className="mt-0.5 text-xs text-slate-400">
              Прошло {monthInfo.elapsed} из {monthInfo.total} дней месяца
            </p>
          </>
        ) : null}

        <div className="mt-4 space-y-3">
          {renderBar('Прошло месяца', monthInfo.pct, 'bg-slate-400')}
          {renderBar(
            'Обязательные',
            essential.pct,
            barColor(essential.pct),
            // Подпись «X из Y» — только в раскрытом виде
            isExpanded
              ? essential.planned > 0
                ? `${formatMoney(essential.spent)} из ${formatMoney(essential.planned)}`
                : 'план не задан'
              : undefined,
          )}
          {renderBar(
            'Второстепенные',
            secondary.pct,
            barColor(secondary.pct),
            isExpanded
              ? secondary.planned > 0
                ? `${formatMoney(secondary.spent)} из ${formatMoney(secondary.planned)}`
                : 'план не задан'
              : undefined,
          )}
        </div>
      </>
    );
  }

  return (
    <div
      ref={wrapperRef}
      className="relative h-full overflow-visible"
      style={wrapperStyle}
    >
      {backdrop}
      <div ref={cardRef}>
        <Card className="relative overflow-visible p-5" style={cardStyle}>
          {renderContent()}
        </Card>
      </div>
    </div>
  );
}
