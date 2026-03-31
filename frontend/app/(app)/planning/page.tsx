"use client";

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  ChevronDown,
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
import { getAccounts } from '@/lib/api/accounts';
import { getBudgetAlerts, getBudgetProgress, markAlertRead, updateBudget } from '@/lib/api/budget';
import { createRealAsset, deleteRealAsset, getRealAssets, updateRealAsset } from '@/lib/api/financial-health';
import { formatMoney } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { toast } from 'sonner';
import type { Account } from '@/types/account';
import type { BudgetAlert, BudgetAlertType, BudgetProgress } from '@/types/budget';
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

// For income: high % = good (green), low % = behind (amber/red)
function incomeBarColor(pct: number) {
  if (pct >= 80) return 'bg-emerald-500';
  if (pct >= 40) return 'bg-amber-400';
  return 'bg-rose-400';
}

function incomePctColor(pct: number) {
  if (pct >= 80) return 'text-emerald-600';
  if (pct >= 40) return 'text-amber-600';
  return 'text-rose-500';
}

// ── Asset type labels ─────────────────────────────────────────────────────────

const ASSET_TYPE_LABELS: Record<RealAssetType, string> = {
  real_estate: 'Недвижимость',
  car: 'Автомобиль',
  other: 'Прочее',
};

const ASSET_TYPE_OPTIONS: RealAssetType[] = ['real_estate', 'car', 'other'];

// ── Credit debt helper ────────────────────────────────────────────────────────

function calcCreditDebt(account: Account): number {
  const balance = Number(account.balance);
  if (account.account_type === 'credit_card') {
    const limit = Number(account.credit_limit_original ?? 0);
    return Math.max(0, limit - balance);
  }
  if (account.account_type === 'credit' || account.is_credit) {
    return Math.max(0, -balance);
  }
  return 0;
}

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

// ── ExpenseGroup ──────────────────────────────────────────────────────────────

const EXP_COL = 'grid-cols-[1fr_130px_130px_130px_180px]';

function ExpenseGroup({
  title,
  items,
  onSave,
}: {
  title: string;
  items: BudgetProgress[];
  onSave: (categoryId: number, amount: number) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [editing, setEditing]     = useState(false);
  const [drafts, setDrafts]       = useState<Record<number, string>>({});

  const groupPlanned = items.reduce((s, i) => s + Number(i.planned_amount), 0);
  const groupSpent   = items.reduce((s, i) => s + Number(i.spent_amount), 0);

  function startEdit() {
    const init: Record<number, string> = {};
    items.forEach(i => { init[i.category_id] = String(Math.round(Number(i.planned_amount))); });
    setDrafts(init);
    setEditing(true);
  }

  function cancel() {
    setEditing(false);
    setDrafts({});
  }

  function saveAll() {
    let hasInvalid = false;
    items.forEach(item => {
      const raw = drafts[item.category_id];
      if (raw === undefined) return;
      const parsed = parseFloat(raw.replace(',', '.'));
      if (!Number.isFinite(parsed) || parsed < 0) {
        toast.error(`Некорректное значение для «${item.category_name}»`);
        hasInvalid = true;
        return;
      }
      if (Math.abs(parsed - Number(item.planned_amount)) >= 0.01) {
        onSave(item.category_id, parsed);
      }
    });
    if (!hasInvalid) {
      setEditing(false);
      setDrafts({});
    }
  }

  return (
    <Card>
      {/* ── Header ── */}
      <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
        <button
          onClick={() => setCollapsed(c => !c)}
          className="flex flex-1 items-center gap-2 text-left min-w-0"
        >
          {collapsed
            ? <ChevronRight className="size-4 shrink-0 text-slate-400" />
            : <ChevronDown  className="size-4 shrink-0 text-slate-400" />
          }
          <span className="text-sm font-semibold text-slate-800">{title}</span>
          {collapsed && (
            <span className="ml-1 truncate text-xs text-slate-400">
              план {formatMoney(groupPlanned)} · факт {formatMoney(groupSpent)}
            </span>
          )}
        </button>

        {!collapsed && (
          <div className="flex shrink-0 items-center gap-2">
            {editing ? (
              <>
                <Button size="sm" variant="secondary" onClick={cancel}>
                  <X className="size-3.5" /> Отмена
                </Button>
                <Button size="sm" onClick={saveAll}>
                  <Check className="size-3.5" /> Сохранить
                </Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" onClick={startEdit}>
                <Pencil className="size-3.5" /> Изменить
              </Button>
            )}
          </div>
        )}
      </div>

      {!collapsed && (
        <>
          {items.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-slate-400">
              Нет категорий расходов в этой группе.
            </div>
          ) : (
            <>
          {/* ── Column headers ── */}
          <div className={cn('hidden gap-3 border-b border-slate-50 px-5 py-2 sm:grid', EXP_COL)}>
            {[
              { label: 'Категория', align: '' },
              { label: 'План',      align: 'text-right' },
              { label: 'Факт',      align: 'text-right' },
              { label: 'Остаток',   align: 'text-right' },
              { label: 'Прогресс', align: '' },
            ].map(h => (
              <p key={h.label} className={cn('text-xs font-medium text-slate-400', h.align)}>{h.label}</p>
            ))}
          </div>

          {/* ── Rows ── */}
          {items.map(item => {
            const planned = Number(item.planned_amount);
            const pct     = planned > 0 ? item.percent_used : 0;
            const barPct  = Math.min(pct, 100);
            const draftVal = drafts[item.category_id] ?? String(Math.round(planned));

            return (
              <div
                key={item.category_id}
                className={cn(
                  'grid items-center gap-x-3 gap-y-1.5 border-b border-slate-50 px-5 py-3 last:border-0',
                  'grid-cols-[1fr_auto] sm:grid-cols-[1fr_130px_130px_130px_180px]',
                )}
              >
                {/* Category */}
                <p className="truncate text-sm font-medium text-slate-900">{item.category_name}</p>

                {/* Plan */}
                <div className="flex justify-end">
                  {editing ? (
                    <Input
                      type="number"
                      min={0}
                      step="any"
                      value={draftVal}
                      onChange={e => setDrafts(prev => ({ ...prev, [item.category_id]: e.target.value }))}
                      className="h-8 w-full rounded-lg px-2 py-1 text-right text-sm"
                    />
                  ) : (
                    <span className="text-sm font-semibold tabular-nums text-slate-900">
                      {formatMoney(planned)}
                    </span>
                  )}
                </div>

                {/* Fact */}
                <p className={cn('hidden text-right text-sm font-semibold tabular-nums sm:block', pctTextColor(pct))}>
                  {formatMoney(item.spent_amount)}
                </p>

                {/* Remaining */}
                <p className={cn('hidden text-right text-sm font-semibold tabular-nums sm:block', Number(item.remaining) < 0 ? 'text-rose-600' : 'text-slate-500')}>
                  {planned > 0 ? formatMoney(item.remaining) : '—'}
                </p>

                {/* Progress */}
                <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
                  {planned > 0 ? (
                    <>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div className={cn('h-full rounded-full transition-all duration-500', barColor(pct))} style={{ width: `${barPct}%` }} />
                      </div>
                      <span className={cn('w-9 shrink-0 text-right text-xs font-semibold tabular-nums', pctTextColor(pct))}>
                        {pct.toFixed(0)}%
                      </span>
                    </>
                  ) : (
                    <span className="text-xs text-slate-400">без плана</span>
                  )}
                </div>
              </div>
            );
          })}

          {/* ── Totals ── */}
          {items.length > 1 && (
            <div className={cn('hidden gap-3 border-t border-slate-100 bg-slate-50/60 px-5 py-3 sm:grid', EXP_COL)}>
              <p className="text-xs font-medium text-slate-500">Итого</p>
              <p className="text-right text-xs font-semibold tabular-nums text-slate-700">{formatMoney(groupPlanned)}</p>
              <p className="text-right text-xs font-semibold tabular-nums text-slate-700">{formatMoney(groupSpent)}</p>
              <p className={cn('text-right text-xs font-semibold tabular-nums', groupSpent > groupPlanned ? 'text-rose-600' : 'text-slate-500')}>
                {groupPlanned > 0 ? formatMoney(groupPlanned - groupSpent) : '—'}
              </p>
              <div />
            </div>
          )}
            </>
          )}
        </>
      )}
    </Card>
  );
}

// ── IncomeGroup ───────────────────────────────────────────────────────────────

function IncomeGroup({
  label,
  items,
  onSave,
}: {
  label: string;
  items: BudgetProgress[];
  onSave: (categoryId: number, amount: number) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [editing, setEditing]     = useState(false);
  const [drafts, setDrafts]       = useState<Record<number, string>>({});

  const groupPlanned = items.reduce((s, i) => s + Number(i.planned_amount), 0);
  const groupSpent   = items.reduce((s, i) => s + Number(i.spent_amount), 0);

  function startEdit() {
    const init: Record<number, string> = {};
    items.forEach(i => { init[i.category_id] = String(Math.round(Number(i.planned_amount))); });
    setDrafts(init);
    setEditing(true);
  }

  function cancel() {
    setEditing(false);
    setDrafts({});
  }

  function saveAll() {
    let hasInvalid = false;
    items.forEach(item => {
      const raw = drafts[item.category_id];
      if (raw === undefined) return;
      const parsed = parseFloat(raw.replace(',', '.'));
      if (!Number.isFinite(parsed) || parsed < 0) {
        toast.error(`Некорректное значение для «${item.category_name}»`);
        hasInvalid = true;
        return;
      }
      if (Math.abs(parsed - Number(item.planned_amount)) >= 0.01) {
        onSave(item.category_id, parsed);
      }
    });
    if (!hasInvalid) {
      setEditing(false);
      setDrafts({});
    }
  }

  return (
    <Card>
      {/* ── Header ── */}
      <div className="flex items-center gap-2 border-b border-slate-100 px-5 py-3">
        <button
          onClick={() => setCollapsed(c => !c)}
          className="flex flex-1 items-center gap-2 text-left min-w-0"
        >
          {collapsed
            ? <ChevronRight className="size-4 shrink-0 text-slate-400" />
            : <ChevronDown  className="size-4 shrink-0 text-slate-400" />
          }
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
          {collapsed && items.length > 0 && (
            <span className="ml-1 truncate text-xs text-slate-400">
              план {formatMoney(groupPlanned)} · факт {formatMoney(groupSpent)}
            </span>
          )}
        </button>

        {!collapsed && items.length > 0 && (
          <div className="flex shrink-0 items-center gap-2">
            {editing ? (
              <>
                <Button size="sm" variant="secondary" onClick={cancel}>
                  <X className="size-3.5" /> Отмена
                </Button>
                <Button size="sm" onClick={saveAll}>
                  <Check className="size-3.5" /> Сохранить
                </Button>
              </>
            ) : (
              <Button size="sm" variant="secondary" onClick={startEdit}>
                <Pencil className="size-3.5" /> Изменить
              </Button>
            )}
          </div>
        )}
      </div>

      {!collapsed && (
        <>
          {items.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-slate-400">
              Нет категорий доходов. Добавьте категории в разделе{' '}
              <span className="font-medium text-slate-600">Категории</span>.
            </div>
          ) : (
            <>
              {/* Column headers */}
              <div className="hidden grid-cols-[1fr_130px_130px_130px_180px] gap-3 border-b border-slate-50 px-5 py-2 sm:grid">
                {['Категория', 'План', 'Факт', 'Остаток', 'Прогресс'].map(h => (
                  <p key={h} className={cn('text-xs font-medium text-slate-400', h !== 'Категория' && h !== 'Прогресс' ? 'text-right' : '')}>{h}</p>
                ))}
              </div>

              {/* Rows */}
              {items.map(item => {
                const planned  = Number(item.planned_amount);
                const pct      = item.percent_used;
                const barPct   = Math.min(pct, 100);
                const draftVal = drafts[item.category_id] ?? String(Math.round(planned));

                return (
                  <div
                    key={item.category_id}
                    className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 border-b border-slate-50 px-5 py-3 last:border-0 sm:grid-cols-[1fr_130px_130px_130px_180px]"
                  >
                    <p className="truncate text-sm font-medium text-slate-900">{item.category_name}</p>

                    {/* Plan */}
                    <div className="flex justify-end">
                      {editing ? (
                        <Input
                          type="number"
                          min={0}
                          step="any"
                          value={draftVal}
                          onChange={e => setDrafts(prev => ({ ...prev, [item.category_id]: e.target.value }))}
                          className="h-8 w-full rounded-lg px-2 py-1 text-right text-sm"
                        />
                      ) : (
                        <span className="text-sm font-semibold tabular-nums text-slate-900">
                          {formatMoney(planned)}
                        </span>
                      )}
                    </div>

                    {/* Fact */}
                    <p className="hidden text-right text-sm font-semibold tabular-nums text-emerald-600 sm:block">
                      {formatMoney(item.spent_amount)}
                    </p>

                    {/* Remaining */}
                    <p className={cn('hidden text-right text-sm font-semibold tabular-nums sm:block', Number(item.remaining) > 0 ? 'text-slate-500' : 'text-emerald-600')}>
                      {formatMoney(Number(item.remaining))}
                    </p>

                    {/* Progress */}
                    <div className="col-span-2 flex items-center gap-2 sm:col-span-1">
                      {planned > 0 ? (
                        <>
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                            <div className={cn('h-full rounded-full transition-all duration-500', incomeBarColor(pct))} style={{ width: `${barPct}%` }} />
                          </div>
                          <span className={cn('w-9 shrink-0 text-right text-xs font-semibold tabular-nums', incomePctColor(pct))}>
                            {pct.toFixed(0)}%
                          </span>
                        </>
                      ) : (
                        <span className="text-xs text-slate-400">без плана</span>
                      )}
                    </div>
                  </div>
                );
              })}

              {/* Totals */}
              {items.length > 1 && (
                <div className="hidden grid-cols-[1fr_130px_130px_130px_180px] gap-3 border-t border-slate-100 bg-slate-50/60 px-5 py-3 sm:grid">
                  <p className="text-xs font-medium text-slate-500">Итого</p>
                  <p className="text-right text-xs font-semibold tabular-nums text-slate-700">{formatMoney(groupPlanned)}</p>
                  <p className="text-right text-xs font-semibold tabular-nums text-emerald-600">{formatMoney(groupSpent)}</p>
                  <p className="text-right text-xs font-semibold tabular-nums text-slate-500">
                    {formatMoney(items.reduce((s, i) => s + Number(i.remaining), 0))}
                  </p>
                  <div />
                </div>
              )}
            </>
          )}
        </>
      )}
    </Card>
  );
}

// ── RealAsset form ────────────────────────────────────────────────────────────

const EMPTY_FORM: RealAssetPayload = { asset_type: 'real_estate', name: '', estimated_value: 0, linked_account_id: null };

function RealAssetForm({
  initial,
  creditAccounts,
  onSave,
  onCancel,
  isSaving,
}: {
  initial: RealAssetPayload;
  creditAccounts: Account[];
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
      {creditAccounts.length > 0 && (
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-500">Привязанный кредит</label>
          <Select
            value={form.linked_account_id ?? ''}
            onChange={(e) => set('linked_account_id', e.target.value ? Number(e.target.value) : null)}
            disabled={isSaving}
          >
            <option value="">— не привязан —</option>
            {creditAccounts.map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </Select>
        </div>
      )}
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

  const assetsQuery = useQuery({
    queryKey: ['real-assets'],
    queryFn: getRealAssets,
  });

  const accountsQuery = useQuery({
    queryKey: ['accounts'],
    queryFn: getAccounts,
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
  const creditAccounts = (accountsQuery.data ?? []).filter(
    (a: Account) => a.account_type === 'credit',
  );
  const expenseItems         = items.filter(i => i.category_kind === 'expense' && !i.exclude_from_planning);
  const excludedExpenseItems = items.filter(i => i.category_kind === 'expense' && i.exclude_from_planning);
  const incomeItems          = items.filter(i => i.category_kind === 'income');
  const activeIncomeItems  = incomeItems.filter(i => i.category_priority === 'income_active');
  const passiveIncomeItems = incomeItems.filter(i => i.category_priority === 'income_passive');

  const totalPlanned      = expenseItems.reduce((s, i) => s + Number(i.planned_amount), 0);
  const totalSpent        = expenseItems.reduce((s, i) => s + Number(i.spent_amount), 0);
  const totalPlannedIncome = incomeItems.reduce((s, i) => s + Number(i.planned_amount), 0);
  const budgetPct         = totalPlanned > 0 ? (totalSpent / totalPlanned) * 100 : null;

  const projectedBalance = totalPlannedIncome - totalPlanned;

  const isFuture = selectedMonth > CURRENT_MONTH;
  const isCurrent = selectedMonth === CURRENT_MONTH;

  // Month navigation
  const nextKey = shiftMonthKey(selectedMonth, 1);
  const { year: ny, month: nm } = parseMonthKey(nextKey);
  const canGoNext =
    ny < _today.getFullYear() ||
    (ny === _today.getFullYear() && nm <= _today.getMonth() + 2);

  // Visible expense items: skip rows where plan=0 AND fact=0
  const visibleExpenseItems = expenseItems.filter(
    i => Number(i.planned_amount) > 0 || Number(i.spent_amount) > 0,
  );
  const essentialItems = visibleExpenseItems.filter(i => i.category_priority === 'expense_essential');
  const secondaryItems = visibleExpenseItems.filter(i => i.category_priority === 'expense_secondary');
  const otherExpItems  = visibleExpenseItems.filter(i => i.category_priority !== 'expense_essential' && i.category_priority !== 'expense_secondary');

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

      {/* ── Summary ───────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-stretch gap-4">
        <Card className="p-5" style={{ flex: '1 1 0' }}>
          <p className="text-xs font-medium text-slate-500">Доходы за месяц</p>
          {budgetQuery.isLoading ? (
            <div className="mt-2 h-7 w-28 animate-pulse rounded bg-slate-100" />
          ) : (
            <p className="mt-2 text-xl font-semibold text-emerald-600 tabular-nums">{formatMoney(totalPlannedIncome)}</p>
          )}
          <p className="mt-1 text-xs text-slate-400">по плановым данным</p>
        </Card>

        <Card className="p-5" style={{ flex: '1 1 0' }}>
          <p className="text-xs font-medium text-slate-500">Расходы за месяц</p>
          {budgetQuery.isLoading ? (
            <div className="mt-2 h-7 w-28 animate-pulse rounded bg-slate-100" />
          ) : (
            <p className="mt-2 text-xl font-semibold text-rose-600 tabular-nums">{formatMoney(totalPlanned)}</p>
          )}
          <p className="mt-1 text-xs text-slate-400">по плановым данным</p>
        </Card>

        <Card className="p-5" style={{ flex: '1 1 0' }}>
          <p className="text-xs font-medium text-slate-500">Прогноз остатка</p>
          {budgetQuery.isLoading ? (
            <div className="mt-2 h-7 w-28 animate-pulse rounded bg-slate-100" />
          ) : (
            <p className={cn('mt-2 text-xl font-semibold tabular-nums', projectedBalance >= 0 ? 'text-slate-950' : 'text-rose-600')}>
              {formatMoney(projectedBalance)}
            </p>
          )}
          <p className="mt-1 text-xs text-slate-400">плановые доходы − расходы</p>
        </Card>

        <Card className="p-5" style={{ flex: '1 1 0' }}>
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

      {/* ── Income block ──────────────────────────────────────────────────── */}
      {!budgetQuery.isLoading && (
        <div>
          <h3 className="mb-3 text-lg font-semibold text-slate-950">Доходы</h3>
          <div className="space-y-4">
            <IncomeGroup label="Активные доходы"  items={activeIncomeItems}  onSave={(id, amount) => updateBudgetMutation.mutate({ categoryId: id, amount })} />
            <IncomeGroup label="Пассивные доходы" items={passiveIncomeItems} onSave={(id, amount) => updateBudgetMutation.mutate({ categoryId: id, amount })} />
          </div>
        </div>
      )}

      {/* ── Expense groups (table view) ────────────────────────────────────── */}
      {budgetQuery.isLoading && (
        <Card className="p-5">
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="h-3.5 flex-1 animate-pulse rounded bg-slate-100" />
                <div className="h-3.5 w-20 animate-pulse rounded bg-slate-100" />
                <div className="h-3.5 w-20 animate-pulse rounded bg-slate-100" />
                <div className="h-3.5 w-32 animate-pulse rounded bg-slate-100" />
              </div>
            ))}
          </div>
        </Card>
      )}

      {budgetQuery.isError && (
        <Card className="p-6 text-center text-sm text-rose-600">Не удалось загрузить данные бюджета.</Card>
      )}

      {!budgetQuery.isLoading && !budgetQuery.isError && (
        <div className="space-y-4">
          <ExpenseGroup title="Обязательные расходы"   items={essentialItems} onSave={(id, amount) => updateBudgetMutation.mutate({ categoryId: id, amount })} />
          <ExpenseGroup title="Второстепенные расходы" items={secondaryItems} onSave={(id, amount) => updateBudgetMutation.mutate({ categoryId: id, amount })} />
          <ExpenseGroup title="Прочие расходы"         items={otherExpItems}  onSave={(id, amount) => updateBudgetMutation.mutate({ categoryId: id, amount })} />
        </div>
      )}

      {/* ── Excluded expense categories (one-time outflows) ───────────────── */}
      {!budgetQuery.isLoading && excludedExpenseItems.length > 0 && (
        <Card>
          <div className="border-b border-slate-100 px-5 py-3">
            <p className="text-sm font-semibold text-slate-700">Имущество и крупные покупки</p>
            <p className="mt-0.5 text-xs text-slate-400">исключено из аналитики бюджета</p>
          </div>
          {excludedExpenseItems.map((item) => (
            <div
              key={item.category_id}
              className="flex items-center justify-between gap-4 border-b border-slate-50 px-5 py-3 last:border-0"
            >
              <p className="truncate text-sm font-medium text-slate-700">{item.category_name}</p>
              <p className="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
                {formatMoney(item.spent_amount)}
              </p>
            </div>
          ))}
          {excludedExpenseItems.length > 1 && (
            <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50/60 px-5 py-3">
              <p className="text-xs font-medium text-slate-500">Итого</p>
              <p className="text-sm font-semibold tabular-nums text-slate-900">
                {formatMoney(excludedExpenseItems.reduce((s, i) => s + Number(i.spent_amount), 0))}
              </p>
            </div>
          )}
        </Card>
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
              creditAccounts={creditAccounts}
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
              {(assetsQuery.data ?? []).map((asset: RealAsset) => {
                const linkedAccount = asset.linked_account_id
                  ? creditAccounts.find((a: Account) => a.id === asset.linked_account_id)
                  : null;
                const debt = linkedAccount ? calcCreditDebt(linkedAccount) : 0;
                const netValue = Number(asset.estimated_value) - debt;
                return (
                <div key={asset.id} className="px-5 py-4">
                  <div className="flex items-center gap-4">
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
                          initial: { asset_type: asset.asset_type, name: asset.name, estimated_value: Number(asset.estimated_value), linked_account_id: asset.linked_account_id ?? null },
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
                  {linkedAccount && (
                    <p className="mt-1.5 text-xs text-slate-500">
                      Кредит: <span className="font-medium text-slate-700">{linkedAccount.name}</span>
                      {' · '}остаток долга: <span className="font-medium text-rose-600 tabular-nums">{formatMoney(debt)}</span>
                      {' · '}чистая стоимость: <span className="font-medium text-emerald-700 tabular-nums">{formatMoney(netValue)}</span>
                    </p>
                  )}
                </div>
                );
              })}

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
