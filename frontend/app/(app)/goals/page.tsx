'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Archive, Lock, MoreHorizontal, Pencil, Plus, Shield, Target } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  archiveGoal,
  createGoal,
  getGoalForecast,
  getGoals,
  updateGoal,
} from '@/lib/api/goals';
import { getCategories } from '@/lib/api/categories';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type {
  CreateGoalPayload,
  GoalForecastResponse,
  GoalWithProgress,
} from '@/types/goal';

type GoalFormSubmitValues = {
  name: string;
  target_amount: number;
  deadline: string | null;
  category_id: number | null;
};

function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 19) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function monthsLabel(n: number) {
  return `${n} ${plural(n, 'месяц', 'месяца', 'месяцев')}`;
}

function formatMonthYear(value: string) {
  return new Date(value).toLocaleDateString('ru-RU', {
    month: 'long',
    year: 'numeric',
  });
}

function isDateInPast(dateString: string): boolean {
  if (!dateString) return false;
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  return dateString <= todayStr;
}

function getMinDeadline(): string {
  const today = new Date();
  const nextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  return nextMonth.toISOString().split('T')[0];
}

function GoalFormModal({
  initial,
  onClose,
  onSubmit,
  isSubmitting,
}: {
  initial?: GoalWithProgress | null;
  onClose: () => void;
  onSubmit: (values: GoalFormSubmitValues) => void;
  isSubmitting: boolean;
}) {
  const [name, setName] = useState(initial?.name ?? '');
  const [targetAmount, setTargetAmount] = useState(
    initial ? String(initial.target_amount) : ''
  );
  const [deadline, setDeadline] = useState(initial?.deadline ?? '');
  const [deadlineError, setDeadlineError] = useState<string | null>(null);
  const [contributionRub, setContributionRub] = useState('');
  const [contributionPct, setContributionPct] = useState('');
  const [forecast, setForecast] = useState<GoalForecastResponse | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [errors, setErrors] = useState<{ name?: string; target_amount?: string }>({});
  const [categoryId, setCategoryId] = useState<string>(
    initial?.category_id ? String(initial.category_id) : ''
  );
  const forecastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data: categories } = useQuery({
    queryKey: ['categories', 'goal-form', 'expense'],
    queryFn: () => getCategories({ kind: 'expense' }),
    staleTime: 1000 * 60 * 5,
  });
  const expenseCategories = categories ?? [];

  function triggerForecast(params: {
    amount: number;
    deadline: string;
    contribution: number | null;
  }) {
    if (forecastTimerRef.current) clearTimeout(forecastTimerRef.current);
    setForecastLoading(true);
    forecastTimerRef.current = setTimeout(async () => {
      if (!params.amount || params.amount <= 0) {
        setForecast(null);
        setForecastLoading(false);
        return;
      }
      if (params.deadline && isDateInPast(params.deadline)) {
        setForecast(null);
        setForecastLoading(false);
        return;
      }
      try {
        const result = await getGoalForecast({
          target_amount: params.amount,
          deadline: params.deadline || null,
          monthly_contribution: params.contribution,
        });
        setForecast(result);
      } catch {
        setForecast(null);
      } finally {
        setForecastLoading(false);
      }
    }, 400);
  }

  function handleContributionRubChange(value: string) {
    setContributionRub(value);
    const smo = forecast?.monthly_avg_balance ?? 0;
    if (smo > 0 && value) {
      const pct = (Number(value) / smo * 100).toFixed(1);
      setContributionPct(pct);
    } else {
      setContributionPct('');
    }
    triggerForecast({
      amount: Number(targetAmount),
      deadline,
      contribution: Number(value) || null,
    });
  }

  function handleContributionPctChange(value: string) {
    setContributionPct(value);
    const smo = forecast?.monthly_avg_balance ?? 0;
    const rub = smo > 0 && value ? Math.round((smo * Number(value)) / 100) : 0;
    setContributionRub(rub > 0 ? String(rub) : '');
    triggerForecast({
      amount: Number(targetAmount),
      deadline,
      contribution: rub || null,
    });
  }

  function handleDeadlineChange(value: string) {
    setDeadline(value);
    if (value && isDateInPast(value)) {
      setDeadlineError('Укажи дату в будущем');
      setForecast(null);
      if (forecastTimerRef.current) clearTimeout(forecastTimerRef.current);
      return;
    }
    setDeadlineError(null);
    triggerForecast({
      amount: Number(targetAmount),
      deadline: value,
      contribution: Number(contributionRub) || null,
    });
  }

  function handleAmountChange(value: string) {
    setTargetAmount(value);
    if (errors.target_amount) {
      setErrors((prev) => ({ ...prev, target_amount: undefined }));
    }
    const amount = Number(value);
    if (!value || amount <= 0) {
      if (forecastTimerRef.current) clearTimeout(forecastTimerRef.current);
      setForecast(null);
      setForecastLoading(false);
      return;
    }
    triggerForecast({
      amount,
      deadline,
      contribution: Number(contributionRub) || null,
    });
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: { name?: string; target_amount?: string } = {};
    if (!name.trim()) nextErrors.name = 'Укажи название';
    if (!targetAmount || Number(targetAmount) <= 0) {
      nextErrors.target_amount = 'Сумма должна быть больше 0';
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    onSubmit({
      name: name.trim(),
      target_amount: Number(targetAmount),
      deadline: deadline || null,
      category_id: categoryId ? Number(categoryId) : null,
    });
  }

  useEffect(() => {
    if (initial && Number(targetAmount) > 0) {
      triggerForecast({
        amount: Number(targetAmount),
        deadline,
        contribution: Number(contributionRub) || null,
      });
    }
    return () => {
      if (forecastTimerRef.current) clearTimeout(forecastTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const smo = forecast?.monthly_avg_balance ?? 0;
    if (smo <= 0) return;

    if (contributionRub) {
      const pct = (Number(contributionRub) / smo * 100).toFixed(1);
      if (pct !== contributionPct) {
        setContributionPct(pct);
      }
      return;
    }

    if (contributionPct) {
      const rub = (smo * Number(contributionPct) / 100).toFixed(0);
      if (rub !== contributionRub) {
        setContributionRub(rub);
        triggerForecast({
          amount: Number(targetAmount),
          deadline,
          contribution: Number(rub),
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forecast?.monthly_avg_balance]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-[28px] bg-white p-6 shadow-2xl">
        <h2 className="mb-5 text-base font-semibold text-slate-950">
          {initial ? 'Редактировать цель' : 'Новая цель'}
        </h2>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div>
            <Label htmlFor="goal-name">Название</Label>
            <Input
              id="goal-name"
              className="mt-1 h-9"
              placeholder="Например: MacBook Pro"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (errors.name) setErrors((prev) => ({ ...prev, name: undefined }));
              }}
            />
            {errors.name ? <p className="mt-1 text-xs text-rose-600">{errors.name}</p> : null}
          </div>

          <div>
            <Label htmlFor="goal-amount">Целевая сумма, ₽</Label>
            <Input
              id="goal-amount"
              className="mt-1 h-9"
              type="number"
              step="0.01"
              placeholder="0.00"
              value={targetAmount}
              onChange={(e) => handleAmountChange(e.target.value)}
            />
            {errors.target_amount ? (
              <p className="mt-1 text-xs text-rose-600">{errors.target_amount}</p>
            ) : null}
          </div>

          <div>
            <Label htmlFor="goal-deadline">Дедлайн</Label>
            <Input
              id="goal-deadline"
              className="mt-1 h-9"
              type="date"
              value={deadline}
              min={getMinDeadline()}
              onChange={(e) => handleDeadlineChange(e.target.value)}
            />
            {deadlineError ? (
              <p className="mt-1 text-xs text-rose-600">{deadlineError}</p>
            ) : null}
          </div>
          {expenseCategories.length > 0 && (
            <div>
              <Label htmlFor="goal-category">Категория расходов (необязательно)</Label>
              <select
                id="goal-category"
                className="mt-1 h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-400"
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                <option value="">— не привязывать —</option>
                {expenseCategories.map((cat) => (
                  <option key={cat.id} value={String(cat.id)}>{cat.name}</option>
                ))}
              </select>
              <p className="mt-1 text-xs text-slate-400">
                Взносы на цель будут отображаться в аналитике в выбранной категории.
              </p>
            </div>
          )}

          <div>
            <Label>Ежемесячный взнос</Label>
            <div className="mt-1 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <Input
                type="number"
                placeholder="₽ сумма"
                value={contributionRub}
                onChange={(e) => handleContributionRubChange(e.target.value)}
              />
              <span className="text-sm text-slate-400">или</span>
              <Input
                type="number"
                placeholder="% от остатка"
                value={contributionPct}
                onChange={(e) => handleContributionPctChange(e.target.value)}
              />
            </div>
          </div>

          {forecast && (
            <div className="relative space-y-2 rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
              {forecastLoading && (
                <div className="absolute inset-x-0 top-0 h-0.5 overflow-hidden rounded-t-2xl">
                  <div className="h-full animate-pulse bg-slate-300" />
                </div>
              )}
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
                Прогноз
              </p>

              <p className="text-sm text-slate-600">
                Твой среднемесячный остаток:{' '}
                <span className="font-medium text-slate-900">
                  {formatMoney(forecast.monthly_avg_balance)}
                </span>
              </p>

              {forecast.monthly_needed != null && (
                <p className="text-sm text-slate-600">
                  Нужно откладывать:{' '}
                  <span className="font-medium text-slate-900">
                    {formatMoney(forecast.monthly_needed)}/мес
                  </span>
                </p>
              )}

              {forecast.estimated_date && (
                <p className="text-sm text-slate-600">
                  При текущем взносе достигнешь:{' '}
                  <span className="font-medium text-slate-900">
                    {formatMonthYear(forecast.estimated_date)}
                  </span>
                  {forecast.estimated_months != null && (
                    <span className="text-slate-400">
                      {' '}({monthsLabel(forecast.estimated_months)})
                    </span>
                  )}
                </p>
              )}

              {forecast.deadline_too_close && (
                <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">
                  Слишком близкий срок — выбери дату минимум через 1 месяц.
                </div>
              )}

              {Number(contributionRub) > forecast.monthly_avg_balance &&
                forecast.monthly_avg_balance > 0 && (
                  <div className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">
                    Взнос превышает среднемесячный остаток на{' '}
                    {formatMoney(Number(contributionRub) - forecast.monthly_avg_balance)}.
                    Уменьши сумму.
                  </div>
                )}

              {!forecast.is_achievable && forecast.shortfall != null && (
                <div className="rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-700">
                  Не хватает {formatMoney(forecast.shortfall)}/мес для достижения в срок.
                  {forecast.suggested_date && (
                    <> Реально — к {formatMonthYear(forecast.suggested_date)}.</>
                  )}
                </div>
              )}

              {forecast.is_achievable && deadline && !forecast.shortfall && (
                <div className="rounded-xl bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                  Цель достижима в срок ✓
                </div>
              )}
            </div>
          )}

          {!forecast && forecastLoading && (
            <div className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
              <div className="space-y-2">
                <div className="h-3 w-24 animate-pulse rounded bg-slate-200" />
                <div className="h-4 w-48 animate-pulse rounded bg-slate-200" />
                <div className="h-4 w-40 animate-pulse rounded bg-slate-200" />
              </div>
            </div>
          )}

          <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end">
            <Button type="button" variant="secondary" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Сохраняем...' : initial ? 'Сохранить' : 'Создать'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function GoalCard({
  goal,
  onEdit,
  onArchive,
}: {
  goal: GoalWithProgress;
  onEdit: (goal: GoalWithProgress) => void;
  onArchive: (goal: GoalWithProgress) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const isAchieved = goal.status === 'achieved';
  const isArchived = goal.status === 'archived';
  const isSystem = goal.is_system;

  return (
    <div
      className={cn(
        'relative flex flex-col gap-3 rounded-[28px] bg-white p-5 shadow-sm',
        isAchieved && 'ring-2 ring-amber-300',
        isArchived && 'opacity-60',
        isSystem && 'border border-sky-100 bg-sky-50/40'
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-2">
          <p className="text-sm font-semibold leading-snug text-slate-900">{goal.name}</p>
          {isSystem ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700">
              <Shield className="size-3.5" />
              Системная цель
            </span>
          ) : null}
        </div>
        {!isSystem ? (
          <div className="relative shrink-0">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              className="flex size-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
            >
              <MoreHorizontal className="size-4" />
            </button>
            {menuOpen ? (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-8 z-20 min-w-[160px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-md">
                  {!isArchived ? (
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        setMenuOpen(false);
                        onEdit(goal);
                      }}
                    >
                      <Pencil className="size-3.5" /> Редактировать
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
                    onClick={() => {
                      setMenuOpen(false);
                      onArchive(goal);
                    }}
                  >
                    <Archive className="size-3.5" /> Архивировать
                  </button>
                </div>
              </>
            ) : null}
          </div>
        ) : (
          <div className="flex size-7 items-center justify-center rounded-full bg-white text-sky-500">
            <Lock className="size-4" />
          </div>
        )}
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span
            className={cn(
              'text-xl font-bold tabular-nums',
              isAchieved ? 'text-amber-500' : 'text-slate-900'
            )}
          >
            {goal.percent.toFixed(0)}%
          </span>
          {isAchieved ? (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
              Цель достигнута
            </span>
          ) : null}
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={cn(
              'h-full rounded-full transition-all duration-500',
              isAchieved ? 'bg-amber-400' : 'bg-emerald-500'
            )}
            style={{ width: `${Math.min(goal.percent, 100)}%` }}
          />
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-xs text-slate-500">
          <span className="font-medium text-slate-700">{formatMoney(goal.saved)}</span> из{' '}
          <span className="font-medium text-slate-700">{formatMoney(goal.target_amount)}</span>
        </p>
        {goal.deadline ? (
          <p className="text-xs text-slate-500">
            До дедлайна:{' '}
            <span className="font-medium text-slate-700">
              {(() => {
                const now = new Date();
                const deadlineDate = new Date(goal.deadline);
                const months =
                  (deadlineDate.getFullYear() - now.getFullYear()) * 12 +
                  (deadlineDate.getMonth() - now.getMonth());
                return months > 0 ? monthsLabel(months) : deadlineDate.toLocaleDateString('ru-RU');
              })()}
            </span>
          </p>
        ) : null}
        {goal.monthly_needed != null && goal.monthly_needed > 0 ? (
          <p className="text-xs text-slate-500">
            Откладывать:{' '}
            <span className="font-medium text-emerald-600">
              {formatMoney(goal.monthly_needed)}/мес
            </span>
          </p>
        ) : null}
      </div>

      {!goal.is_system && goal.deadline && goal.is_on_track === false && goal.shortfall != null && (
        <p className="text-xs text-amber-600">
          Отстаёшь — не хватает {formatMoney(goal.shortfall)}/мес
        </p>
      )}
      {!goal.is_system && goal.deadline && goal.is_on_track === true && (
        <p className="text-xs text-emerald-600">На треке ✓</p>
      )}
      {!goal.is_system && !goal.deadline && goal.estimated_date && (
        <p className="text-xs text-slate-400">При текущем темпе — {formatMonthYear(goal.estimated_date)}</p>
      )}

      {isSystem ? (
        <div className="mt-1 rounded-2xl bg-white/80 px-3 py-2 text-xs text-slate-500">
          Эта цель поддерживается системой и автоматически пересчитывает рекомендуемый размер подушки.
        </div>
      ) : null}
    </div>
  );
}

export default function GoalsPage() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editingGoal, setEditingGoal] = useState<GoalWithProgress | null>(null);

  const { data: goals, isLoading } = useQuery({
    queryKey: ['goals'],
    queryFn: getGoals,
  });

  const createMutation = useMutation({
    mutationFn: createGoal,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goals'] });
      setShowModal(false);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Parameters<typeof updateGoal>[1] }) =>
      updateGoal(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goals'] });
      setEditingGoal(null);
    },
  });

  const archiveMutation = useMutation({
    mutationFn: archiveGoal,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goals'] });
    },
  });

  function handleCreateSubmit(values: GoalFormSubmitValues) {
    const payload: CreateGoalPayload = {
      name: values.name,
      target_amount: values.target_amount,
      deadline: values.deadline,
      category_id: values.category_id,
    };
    createMutation.mutate(payload);
  }

  function handleEditSubmit(values: GoalFormSubmitValues) {
    if (!editingGoal) return;
    updateMutation.mutate({
      id: editingGoal.id,
      payload: {
        name: values.name,
        target_amount: values.target_amount,
        deadline: values.deadline,
        category_id: values.category_id,
      },
    });
  }

  const visibleGoals = useMemo(
    () => goals?.filter((goal) => goal.status !== 'archived') ?? [],
    [goals]
  );
  const archivedGoals = useMemo(
    () => goals?.filter((goal) => goal.status === 'archived') ?? [],
    [goals]
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-950">Мои цели</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Финансовые цели и прогресс их достижения
          </p>
        </div>
        <Button onClick={() => setShowModal(true)} className="shrink-0">
          <Plus className="mr-1.5 size-4" /> Новая цель
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="space-y-3 rounded-[28px] bg-white p-5 shadow-sm">
              <div className="h-4 w-40 animate-pulse rounded bg-slate-100" />
              <div className="h-2 w-full animate-pulse rounded-full bg-slate-100" />
              <div className="h-3 w-32 animate-pulse rounded bg-slate-100" />
            </div>
          ))}
        </div>
      ) : null}

      {!isLoading && visibleGoals.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/60 py-20 text-center">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-slate-100">
            <Target className="size-7 text-slate-400" />
          </div>
          <p className="mt-4 text-base font-medium text-slate-600">У вас пока нет целей</p>
          <p className="mt-1 text-sm text-slate-400">
            Поставьте финансовую цель и отслеживайте прогресс
          </p>
          <Button className="mt-5" onClick={() => setShowModal(true)}>
            <Plus className="mr-1.5 size-4" /> Создать первую цель
          </Button>
        </div>
      ) : null}

      {!isLoading && visibleGoals.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {visibleGoals.map((goal) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              onEdit={setEditingGoal}
              onArchive={(item) => archiveMutation.mutate(item.id)}
            />
          ))}
        </div>
      ) : null}

      {!isLoading && archivedGoals.length > 0 ? (
        <details className="group">
          <summary className="flex cursor-pointer items-center gap-2 select-none text-sm font-medium text-slate-400">
            <Archive className="size-4" /> Архив ({archivedGoals.length})
          </summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {archivedGoals.map((goal) => (
              <GoalCard
                key={goal.id}
                goal={goal}
                onEdit={setEditingGoal}
                onArchive={(item) => archiveMutation.mutate(item.id)}
              />
            ))}
          </div>
        </details>
      ) : null}

      {showModal ? (
        <GoalFormModal
          onClose={() => setShowModal(false)}
          onSubmit={handleCreateSubmit}
          isSubmitting={createMutation.isPending}
        />
      ) : null}
      {editingGoal ? (
        <GoalFormModal
          initial={editingGoal}
          onClose={() => setEditingGoal(null)}
          onSubmit={handleEditSubmit}
          isSubmitting={updateMutation.isPending}
        />
      ) : null}
    </div>
  );
}
