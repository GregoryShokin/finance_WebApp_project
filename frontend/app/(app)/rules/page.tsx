"use client";

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';
import { PageShell } from '@/components/layout/page-shell';
import { EmptyState, ErrorState, LoadingState } from '@/components/states/page-state';
import { Card } from '@/components/ui/card';
import { Select } from '@/components/ui/select';
import { StatCard } from '@/components/shared/stat-card';
import { getCategoryRules } from '@/lib/api/category-rules';
import { getCategories } from '@/lib/api/categories';
import type { CategoryRule, RuleScope } from '@/types/category-rule';

type ScopeFilter = 'all' | RuleScope;
type ActiveFilter = 'all' | 'active' | 'inactive';

const SCOPE_LABEL: Record<RuleScope, string> = {
  exact: 'Точный',
  bank: 'По банку',
  global: 'Глобальный',
  legacy_pattern: 'Legacy',
};

export default function Page() {
  const [scope, setScope] = useState<ScopeFilter>('all');
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>('all');

  const rulesQuery = useQuery({
    queryKey: ['category-rules', { scope, activeFilter }],
    queryFn: () =>
      getCategoryRules({
        scope: scope === 'all' ? undefined : scope,
        is_active:
          activeFilter === 'all' ? undefined : activeFilter === 'active',
      }),
  });

  const categoriesQuery = useQuery({
    queryKey: ['categories'],
    queryFn: () => getCategories(),
  });

  const categoryById = useMemo(() => {
    const map = new Map<number, string>();
    for (const cat of categoriesQuery.data ?? []) {
      map.set(cat.id, cat.name);
    }
    return map;
  }, [categoriesQuery.data]);

  const stats = useMemo(() => {
    const all = rulesQuery.data ?? [];
    return {
      total: all.length,
      active: all.filter((r) => r.is_active).length,
      inactive: all.filter((r) => !r.is_active).length,
      legacy: all.filter((r) => r.scope === 'legacy_pattern').length,
    };
  }, [rulesQuery.data]);

  return (
    <PageShell
      title="Правила категоризации"
      description="Правила создаются автоматически из ваших подтверждённых импортов. Показываются рейтинги подтверждений и отказов — можно сразу увидеть, какие правила надёжные, а какие нет."
    >
      <div className="grid gap-4 md:grid-cols-4">
        <StatCard label="Всего правил" value={String(stats.total)} />
        <StatCard label="Активные" value={String(stats.active)} />
        <StatCard label="Неактивные" value={String(stats.inactive)} />
        <StatCard label="Legacy" value={String(stats.legacy)} />
      </div>

      <Card className="p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">Область:</span>
            <Select
              value={scope}
              onChange={(e) => setScope(e.target.value as ScopeFilter)}
            >
              <option value="all">Все</option>
              <option value="exact">Точный</option>
              <option value="bank">По банку</option>
              <option value="global">Глобальный</option>
              <option value="legacy_pattern">Legacy</option>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-slate-500">Статус:</span>
            <Select
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value as ActiveFilter)}
            >
              <option value="all">Все</option>
              <option value="active">Активные</option>
              <option value="inactive">Неактивные</option>
            </Select>
          </div>
        </div>

        {rulesQuery.isLoading ? (
          <LoadingState />
        ) : rulesQuery.error ? (
          <ErrorState title="Не удалось загрузить правила" description={String(rulesQuery.error)} />
        ) : !rulesQuery.data?.length ? (
          <EmptyState
            title="Правил пока нет"
            description="Правила будут появляться автоматически по мере импорта выписок и подтверждения категорий."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-400">
                  <th className="pb-3 pr-4">Описание</th>
                  <th className="pb-3 pr-4">Категория</th>
                  <th className="pb-3 pr-4">Область</th>
                  <th className="pb-3 pr-4">Подтверждений</th>
                  <th className="pb-3 pr-4">Отказов</th>
                  <th className="pb-3 pr-4">Статус</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rulesQuery.data.map((rule) => (
                  <RuleRow
                    key={rule.id}
                    rule={rule}
                    categoryName={categoryById.get(rule.category_id) ?? `#${rule.category_id}`}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </PageShell>
  );
}

function RuleRow({ rule, categoryName }: { rule: CategoryRule; categoryName: string }) {
  return (
    <tr className="text-slate-700">
      <td className="py-3 pr-4">
        <div className="max-w-md truncate font-medium text-slate-900" title={rule.normalized_description}>
          {rule.normalized_description || '—'}
        </div>
        {rule.identifier_key && rule.identifier_value ? (
          <div className="mt-0.5 text-xs text-slate-400">
            {rule.identifier_key}: {rule.identifier_value}
          </div>
        ) : null}
      </td>
      <td className="py-3 pr-4">{categoryName}</td>
      <td className="py-3 pr-4">
        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
          {SCOPE_LABEL[rule.scope] ?? rule.scope}
        </span>
      </td>
      <td className="py-3 pr-4 tabular-nums">{rule.confirms}</td>
      <td className="py-3 pr-4 tabular-nums">{rule.rejections}</td>
      <td className="py-3 pr-4">
        {rule.is_active ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-600">
            <CheckCircle2 className="size-3.5" />
            Активно
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-slate-400">
            <XCircle className="size-3.5" />
            Неактивно
          </span>
        )}
      </td>
    </tr>
  );
}
