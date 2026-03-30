"use client";

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react';
import { PageShell } from '@/components/layout/page-shell';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { getBudgetAlerts, getBudgetProgress, markAlertRead, updateBudget } from '@/lib/api/budget';
import { createRealAsset, deleteRealAsset, getRealAssets, updateRealAsset } from '@/lib/api/financial-health';
import { getTransactions } from '@/lib/api/transactions';
import { formatMoney } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { toast } from 'sonner';
import type { BudgetAlert, BudgetAlertType } from '@/types/budget';
import type { RealAsset, RealAssetPayload, RealAssetType } from '@/types/financial-health';

// ── Month helpers ─────────────────────────────────────────────────────────────

function toMonthKey(year: number, month: number) {
  return `${year}-${String(month).padStart(2, '0')}-01`;
}

function parseMonthKey(key: string) {
  const [y, m] = key.split('-').map(Number);
  return { year: y, month: m };
}

function shiftMonthKey(key: string, delta: number) {
  const { year, month } = parseMonthKey(key);
  const d = new Date(year, month - 1 + delta, 1);
  return toMonthKey(d.getFullYear(), d.getMonth() + 1);
}

function monthLabel(key: string) {
  const { year, month } = parseMonthKey(key);
  return new Date(year, month - 1, 1).toLocaleString('ru-RU', { month: 'long', year: 'numeric' });
}

function monthDateRange(key: string): { from: string; to: string; daysInMonth: number; daysPassed: number } {
  const { year, month } = parseMonthKey(key);
  const from = `${year}-${String(month).padStart(2, '0')}-01`;
  const daysInMonth = new Date(year, month, 0).getDate();
  const isCurrentMonth = key === CURRENT_MONTH;
  const isFuture = key > CURRENT_MONTH;
  const daysPassed = isCurrentMonth ? _today.getDate() : isFuture ? 0 : daysInMonth;
  const todayStr = _today.toISOString().split('T')[0];
  const lastStr = `${year}-${String(month).padStart(2, '0')}-${String(daysInMonth).padStart(2, '0')}`;
  return { from, to: isCurrentMonth ? todayStr : lastStr, daysInMonth, daysPassed };
}

const _today = new Date();
const CURRENT_MONTH = toMonthKey(_today.getFullYear(), _today.getMonth() + 1);

// ── Alert helpers ─────────────────────────────────────────────────────────────

function alertStyle(type: BudgetAlertType) {
  const isDanger = type === 'anomaly';
  return isDanger
    ? { card: 'border-rose-200 bg-rose-50', icon: 'text-rose-500', title: 'text-rose-900', msg: 'text-rose-700', btn: 'text-rose-400 hover:text-rose-600 hover:bg-rose-100' }
    : { card: 'border-amber-200 bg-amber-50', icon: 'text-amber-500', title: 'text-amber-900', msg: 'text-amber-700', btn: 'text-amber-400 hover:text-amber-600 hover:bg-amber-100' };
}

function alertTitle(type: BudgetAlertType) {
  if (type === 'budget_80_percent') return 'Бюджет почти исчерпан';
  if (type === 'anomaly') return 'Аномальные расходы';
  return 'Прогноз дефицита';
}

// ── Budget bar helpers ────────────────────────────────────────────────────────

function barColor(pct: number) {
  if (pct >= 90) return 'bg-rose-500';
  if (pct >= 70) return 'bg-amber-400';
  return 'bg-emerald-500';
}

function pctTextColor(pct: number) {
  if (pct >= 90) return 'text-rose-600';
  if (pct >= 70) return 'text-amber-600';
  return 'text-emerald-600';
}

// ── Asset type labels ─────────────────────────────────────────────────────────

const ASSET_TYPE_LABELS: Record<RealAssetType, string> = {
  real_estate: 'Недвижимость',
  car: 'Автомобиль',
  other: 'Прочее',
};

const ASSET_TYPE_OPTIONS: RealAssetType[] = ['real_estate', 'car', 'other'];

// ── EditablePlanned ───────────────────────────────────────────────────────────

function EditablePlanned({
  value,
  onSave,
  isSaving,
}: {
  value: number;
  onSave: (v: number) => void;
  isSaving: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  function startEdit() {
    setDraft(String(Math.round(value)));
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }

  function cancel() { setEditing(false); }

  function commit() {
    const parsed = parseFloat(draft.replace(',', '.'));
    if (!Number.isFinite(parsed) || parsed < 0) { toast.error('Введите корректную сумму'); return; }
    onSave(parsed);
    setEditing(false);
  }

  if (!editing) {
    return (
      <button
        onClick={startEdit}
        className="group flex items-center gap-1 text-sm font-semibold text-slate-900 transition hover:text-slate-600"
        title="Нажми, чтобы изменить план"
      >
        {formatMoney(value)}
        <Pencil className="size-3 opacity-0 transition group-hover:opacity-60" />
      </button>
    );
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); commit(); }} className="flex items-center gap-1.5">
      <Input
        ref={inputRef}
        type="number"
        min={0}
        step="any"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && cancel()}
        className="h-8 w-28 rounded-lg px-2 py-1 text-sm"
        disabled={isSaving}
        autoFocus
      />
      <button type="submit" disabled={isSaving} aria-label="Сохранить"
        className="flex size-7 items-center justify-center rounded-lg bg-emerald-100 text-emerald-700 transition hover:bg-emerald-200 disabled:opacity-50">
        <Check className="size-3.5" />
      </button>
      <button type="button" onClick={cancel} disabled={isSaving} aria-label="Отмена"
        className="flex size-7 items-center justify-center rounded-lg bg-slate-100 text-slate-500 transition hover:bg-slate-200 disabled:opacity-50">
        <X className="size-3.5" />
      </button>
    </form>
  );
}

// ── RealAsset form ────────────────────────────────────────────────────────────

const EMPTY_FORM: RealAssetPayload = { asset_type: 'real_estate', name: '', estimated_value: 0 };

function RealAssetForm({
  initial,
  onSave,
  onCancel,
  isSaving,
}: {
  initial: RealAssetPayload;
  onSave: (data: RealAssetPayload) => void;
  onCancel: () => void;
  isSaving: boolean;
}) {
  const [form, setForm] = useState<RealAssetPayload>(initial);

  function set<K extends keyof RealAssetPayload>(key: K, val: RealAssetPayload[K]) {
    setForm(prev => ({ ...prev, [key]: val }));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) { toast.error('Введите название актива'); return; }
    if (form.estimated_value < 0) { toast.error('Стоимость не может быть отрицательной'); return; }
    onSave(form);
  }

  return (
    <form onSubmit={submit} className="surface-muted space-y-3 rounded-2xl p-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Тип</label>
          <Select
            value={form.asset_type}
            onChange={(e) => set('asset_type', e.target.value as RealAssetType)}
            disabled={isSaving}
          >
            {ASSET_TYPE_OPTIONS.map(t => (
              <option key={t} value={t}>{ASSET_TYPE_LABELS[t]}</option>
            ))}
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Название</label>
          <Input
            value={form.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="Квартира на Ленина"
            disabled={isSaving}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Оценочная стоимость, ₽</label>
          <Input
            type="number"
            min={0}
            step="any"
            value={form.estimated_value || ''}
            onChange={(e) => set('estimated_value', parseFloat(e.target.value) || 0)}
            placeholder="5 000 000"
            disabled={isSaving}
          />
        </div>
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={isSaving}>
          <Check className="size-3.5" /> Сохранить
        </Button>
        <Button type="button" variant="secondary" size="sm" onClick={onCancel} disabled={isSaving}>
          Отмена
        </Button>
      </div>
    </form>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PlanningPage() {
  const queryClient = useQueryClient();
  const [selectedMonth, setSelectedMonth] = useState(CURRENT_MONTH);

  // ── Queries ──────────────────────────────────────────────────────────────
  const budgetQuery = useQuery({
    queryKey: ['budget', selectedMonth],
    queryFn: () => getBudgetProgress(selectedMonth),
  });

  const alertsQuery = useQuery({
    queryKey: ['budget-alerts'],
    queryFn: getBudgetAlerts,
  });

  const { from, to, daysInMonth, daysPassed } = monthDateRange(selectedMonth);
  const txQuery = useQuery({
    queryKey: ['transactions', 'planning-month', selectedMonth],
    queryFn: () => getTransactions({ date_from: from, date_to: to }),
  });

  const assetsQuery = useQuery({
    queryKey: ['real-assets'],
    queryFn: getRealAssets,
  });

  // ── Mutations ─────────────────────────────────────────────────────────────
  const dismissMutation = useMutation({
    mutationFn: (id: number) => markAlertRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['budget-alerts'] }),
  });

  const updateBudgetMutation = useMutation({
    mutationFn: ({ categoryId, amount }: { categoryId: number; amount: number }) =>
      updateBudget(selectedMonth, categoryId, amount),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['budget', selectedMonth] });
      toast.success('Плановая сумма обновлена');
    },
    onError: () => toast.error('Не удалось обновить план'),
  });

  const createAssetMutation = useMutation({
    mutationFn: createRealAsset,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['real-assets'] });
      queryClient.invalidateQueries({ queryKey: ['financial-health'] });
      toast.success('Актив добавлен');
      setAssetForm(null);
    },
    onError: () => toast.error('Не удалось добавить актив'),
  });

  const updateAssetMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<RealAssetPayload> }) =>
      updateRealAsset(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['real-assets'] });
      queryClient.invalidateQueries({ queryKey: ['financial-health'] });
      toast.success('Актив обновлён');
      setAssetForm(null);
    },
    onError: () => toast.error('Не удалось обновить актив'),
  });

  const deleteAssetMutation = useMutation({
    mutationFn: deleteRealAsset,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['real-assets'] });
      queryClient.invalidateQueries({ queryKey: ['financial-health'] });
      toast.success('Актив удалён');
    },
    onError: () => toast.error('Не удалось удалить актив'),
  });

  // ── Local state ───────────────────────────────────────────────────────────
  // assetForm: null = closed, { id: undefined } = new, { id: number } = edit
  const [assetForm, setAssetForm] = useState<{ id?: number; initial: RealAssetPayload } | null>(null);

  // ── Derived data ──────────────────────────────────────────────────────────
  const items = budgetQuery.data ?? [];
  const alerts = alertsQuery.data ?? [];
  const txList = txQuery.data ?? [];

  const totalPlanned = items.reduce((s, i) => s + Number(i.planned_amount), 0);
  const totalSpent = items.reduce((s, i) => s + Number(i.spent_amount), 0);
  const budgetPct = totalPlanned > 0 ? (totalSpent / totalPlanned) * 100 : null;

  const txIncome = txList.filter(t => t.type === 'income' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);
  const txExpense = txList.filter(t => t.type === 'expense' && t.affects_analytics).reduce((s, t) => s + Number(t.amount), 0);

  const isFuture = selectedMonth > CURRENT_MONTH;
  const isCurrent = selectedMonth === CURRENT_MONTH;

  let projectedBalance: number | null = null;
  let projectedLabel = '';
  if (isFuture) {
    // For future: income unknown, show budget-based plan deficit
    projectedBalance = -totalPlanned;
    projectedLabel = 'по плану расходов';
  } else if (isCurrent && daysPassed > 0) {
    projectedBalance = txIncome - (txExpense / daysPassed) * daysInMonth;
    projectedLabel = `прогноз · ${daysPassed} из ${daysInMonth} дн.`;
  } else {
    projectedBalance = txIncome - txExpense;
    projectedLabel = 'фактический результат';
  }

  // Month navigation
  const nextKey = shiftMonthKey(selectedMonth, 1);
  const { year: ny, month: nm } = parseMonthKey(nextKey);
  const canGoNext =
    ny < _today.getFullYear() ||
    (ny === _today.getFullYear() && nm <= _today.getMonth() + 2);

  return (
    <PageShell
      title="Планирование"
      description="Бюджет по категориям, итоги месяца и учёт реальных активов."
    >
      {/* ── Alerts ────────────────────────────────────────────────────────── */}
      {alerts.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {alerts.map((alert: BudgetAlert) => {
            const s = alertStyle(alert.alert_type);
            return (
              <div key={alert.id} className={cn('flex gap-3 rounded-2xl border p-4', s.card)}>
                <AlertTriangle className={cn('mt-0.5 size-4 shrink-0', s.icon)} />
                <div className="min-w-0 flex-1">
                  <p className={cn('text-sm font-semibold', s.title)}>{alertTitle(alert.alert_type)}</p>
                  <p className={cn('mt-1 text-xs leading-5', s.msg)}>{alert.message}</p>
                </div>
                <button
                  onClick={() => dismissMutation.mutate(alert.id)}
                  disabled={dismissMutation.isPending}
                  className={cn('mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg transition', s.btn)}
                  aria-label="Закрыть"
                >
                  <X className="size-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Month switcher ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between gap-4 rounded-2xl border border-white/60 bg-white/70 px-5 py-3 shadow-soft backdrop-blur">
        <Button variant="ghost" size="icon" onClick={() => setSelectedMonth(shiftMonthKey(selectedMonth, -1))} aria-label="Предыдущий месяц">
          <ChevronLeft className="size-5" />
        </Button>
        <div className="text-center">
          <p className="text-base font-semibold capitalize text-slate-950">{monthLabel(selectedMonth)}</p>
          {isCurrent && <p className="text-xs text-slate-400">текущий месяц</p>}
          {isFuture && <p className="text-xs text-slate-400">следующий месяц</p>}
        </div>
        <Button variant="ghost" size="icon" onClick={() => setSelectedMonth(shiftMonthKey(selectedMonth, 1))} disabled={!canGoNext} aria-label="Следующий месяц">
          <ChevronRight className="size-5" />
        </Button>
      </div>

      {/* ── Budget cards ───────────────────────────────────────────────────── */}
      {budgetQuery.isLoading && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="p-5 lg:p-6">
              <div className="h-4 w-2/3 animate-pulse rounded bg-slate-100" />
              <div className="mt-4 h-2.5 w-full animate-pulse rounded-full bg-slate-100" />
              <div className="mt-3 flex gap-4">
                {[1, 2, 3].map(j => <div key={j} className="h-3 flex-1 animate-pulse rounded bg-slate-100" />)}
              </div>
            </Card>
          ))}
        </div>
      )}

      {budgetQuery.isError && (
        <Card className="p-6 text-center text-sm text-rose-600">Не удалось загрузить данные бюджета.</Card>
      )}

      {!budgetQuery.isLoading && !budgetQuery.isError && items.length === 0 && (
        <Card className="p-8 text-center">
          <p className="text-sm font-medium text-slate-700">Нет данных о бюджете</p>
          <p className="mt-1 text-xs text-slate-400">Для {monthLabel(selectedMonth)} нет расходных категорий.</p>
        </Card>
      )}

      {!budgetQuery.isLoading && !budgetQuery.isError && items.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => {
            const pct = item.percent_used;
            const barPct = Math.min(pct, 100);
            const isSaving = updateBudgetMutation.isPending && updateBudgetMutation.variables?.categoryId === item.category_id;
            return (
              <Card key={item.category_id} className="p-5 lg:p-6">
                <div className="flex items-start justify-between gap-3">
                  <h3 className="truncate text-sm font-semibold text-slate-900">{item.category_name}</h3>
                  <span className={cn(
                    'shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums',
                    pctTextColor(pct),
                    pct >= 90 ? 'bg-rose-100' : pct >= 70 ? 'bg-amber-100' : 'bg-emerald-100',
                  )}>
                    {pct.toFixed(0)}%
                  </span>
                </div>
                <div className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div className={cn('h-full rounded-full transition-all duration-500', barColor(pct))} style={{ width: `${barPct}%` }} />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                  <div>
                    <p className="text-xs text-slate-400">план</p>
                    <div className="mt-1 flex justify-center">
                      <EditablePlanned
                        value={Number(item.planned_amount)}
                        isSaving={isSaving}
                        onSave={(amount) => updateBudgetMutation.mutate({ categoryId: item.category_id, amount })}
                      />
                    </div>
                  </div>
                  <div>
                    <p className="text-xs text-slate-400">факт</p>
                    <p className={cn('mt-1 text-sm font-semibold tabular-nums', pctTextColor(pct))}>
                      {formatMoney(item.spent_amount)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-400">остаток</p>
                    <p className={cn('mt-1 text-sm font-semibold tabular-nums', Number(item.remaining) < 0 ? 'text-rose-600' : 'text-slate-700')}>
                      {formatMoney(item.remaining)}
                    </p>
                  </div>
                </div>
                {pct > 100 && (
                  <p className="mt-3 rounded-lg bg-rose-50 px-3 py-1.5 text-center text-xs font-medium text-rose-600">
                    Перерасход {formatMoney(Math.abs(Number(item.remaining)))}
                  </p>
                )}
              </Card>
            );
          })}
        </div>
      )}

      {/* ── Month summary ──────────────────────────────────────────────────── */}
      {!budgetQuery.isLoading && (items.length > 0 || txList.length > 0) && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {/* Income */}
          <Card className="p-5">
            <p className="text-xs font-medium text-slate-500">Доходы за месяц</p>
            {txQuery.isLoading ? (
              <div className="mt-2 h-7 w-28 animate-pulse rounded bg-slate-100" />
            ) : (
              <p className="mt-2 text-xl font-semibold text-emerald-600 tabular-nums">{formatMoney(txIncome)}</p>
            )}
            <p className="mt-1 text-xs text-slate-400">по фактическим данным</p>
          </Card>

          {/* Expense */}
          <Card className="p-5">
            <p className="text-xs font-medium text-slate-500">Расходы за месяц</p>
            {txQuery.isLoading ? (
              <div className="mt-2 h-7 w-28 animate-pulse rounded bg-slate-100" />
            ) : (
              <p className="mt-2 text-xl font-semibold text-rose-600 tabular-nums">{formatMoney(txExpense)}</p>
            )}
            <p className="mt-1 text-xs text-slate-400">включая аналитические</p>
          </Card>

          {/* Projected balance */}
          <Card className="p-5">
            <p className="text-xs font-medium text-slate-500">Прогноз остатка</p>
            {txQuery.isLoading ? (
              <div className="mt-2 h-7 w-28 animate-pulse rounded bg-slate-100" />
            ) : projectedBalance !== null ? (
              <p className={cn('mt-2 text-xl font-semibold tabular-nums', projectedBalance >= 0 ? 'text-slate-950' : 'text-rose-600')}>
                {formatMoney(projectedBalance)}
              </p>
            ) : (
              <p className="mt-2 text-xl font-semibold text-slate-400">—</p>
            )}
            <p className="mt-1 text-xs text-slate-400">{projectedLabel}</p>
          </Card>

          {/* Budget completion */}
          <Card className="p-5">
            <p className="text-xs font-medium text-slate-500">Исполнение бюджета</p>
            {budgetQuery.isLoading ? (
              <div className="mt-2 h-7 w-16 animate-pulse rounded bg-slate-100" />
            ) : budgetPct !== null ? (
              <>
                <p className={cn('mt-2 text-xl font-semibold tabular-nums', pctTextColor(budgetPct))}>
                  {budgetPct.toFixed(0)}%
                </p>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                  <div className={cn('h-full rounded-full transition-all', barColor(budgetPct))} style={{ width: `${Math.min(budgetPct, 100)}%` }} />
                </div>
                <p className="mt-1 text-xs text-slate-400">{formatMoney(totalSpent)} из {formatMoney(totalPlanned)}</p>
              </>
            ) : (
              <p className="mt-2 text-xl font-semibold text-slate-400">—</p>
            )}
          </Card>
        </div>
      )}

      {/* ── Real assets ────────────────────────────────────────────────────── */}
      <div>
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-950">Реальные активы</h3>
            <p className="mt-0.5 text-sm text-slate-500">Недвижимость, автомобили и другое имущество.</p>
          </div>
          {!assetForm && (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setAssetForm({ initial: EMPTY_FORM })}
            >
              <Plus className="size-4" /> Добавить
            </Button>
          )}
        </div>

        <div className="space-y-3">
          {/* Add/Edit form */}
          {assetForm && (
            <RealAssetForm
              initial={assetForm.initial}
              isSaving={createAssetMutation.isPending || updateAssetMutation.isPending}
              onCancel={() => setAssetForm(null)}
              onSave={(data) => {
                if (assetForm.id !== undefined) {
                  updateAssetMutation.mutate({ id: assetForm.id, data });
                } else {
                  createAssetMutation.mutate(data);
                }
              }}
            />
          )}

          {/* List */}
          {assetsQuery.isLoading && (
            <Card className="p-5">
              <div className="space-y-3">
                {[1, 2].map(i => (
                  <div key={i} className="flex items-center justify-between gap-4">
                    <div className="h-4 w-40 animate-pulse rounded bg-slate-100" />
                    <div className="h-4 w-24 animate-pulse rounded bg-slate-100" />
                  </div>
                ))}
              </div>
            </Card>
          )}

          {!assetsQuery.isLoading && (assetsQuery.data ?? []).length === 0 && !assetForm && (
            <Card className="p-6 text-center">
              <p className="text-sm text-slate-500">Реальные активы не добавлены.</p>
              <p className="mt-1 text-xs text-slate-400">Добавь недвижимость, авто или другое имущество для расчёта собственного капитала.</p>
            </Card>
          )}

          {!assetsQuery.isLoading && (assetsQuery.data ?? []).length > 0 && (
            <Card className="divide-y divide-slate-100">
              {(assetsQuery.data ?? []).map((asset: RealAsset) => (
                <div key={asset.id} className="flex items-center gap-4 px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
                        {ASSET_TYPE_LABELS[asset.asset_type] ?? asset.asset_type}
                      </span>
                      <p className="truncate text-sm font-medium text-slate-900">{asset.name}</p>
                    </div>
                  </div>
                  <p className="shrink-0 text-sm font-semibold text-slate-900 tabular-nums">
                    {formatMoney(Number(asset.estimated_value))}
                  </p>
                  <div className="flex shrink-0 gap-1.5">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setAssetForm({
                        id: asset.id,
                        initial: { asset_type: asset.asset_type, name: asset.name, estimated_value: Number(asset.estimated_value) },
                      })}
                      aria-label="Редактировать"
                    >
                      <Pencil className="size-4" />
                    </Button>
                    <Button
                      variant="danger"
                      size="icon"
                      onClick={() => deleteAssetMutation.mutate(asset.id)}
                      disabled={deleteAssetMutation.isPending}
                      aria-label="Удалить"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              ))}

              {/* Assets total */}
              {(assetsQuery.data ?? []).length > 1 && (
                <div className="flex items-center justify-between px-5 py-3">
                  <p className="text-sm font-medium text-slate-500">Итого</p>
                  <p className="text-sm font-semibold text-slate-950 tabular-nums">
                    {formatMoney((assetsQuery.data ?? []).reduce((s, a) => s + Number(a.estimated_value), 0))}
                  </p>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </PageShell>
  );
}
