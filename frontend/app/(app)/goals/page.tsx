'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MoreHorizontal, Target, Plus, Archive, Pencil } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import { getGoals, createGoal, updateGoal, archiveGoal } from '@/lib/api/goals';
import type { GoalWithProgress, CreateGoalPayload } from '@/types/goal';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

// ── Helpers ───────────────────────────────────────────────────────────────────

function plural(n: number, one: string, few: string, many: string) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 19) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
}

function monthsLabel(n: number) {
  return `${n} ${plural(n, '\u043c\u0435\u0441\u044f\u0446', '\u043c\u0435\u0441\u044f\u0446\u0430', '\u043c\u0435\u0441\u044f\u0446\u0435\u0432')}`;
}


type Tone = 'good' | 'warning' | 'danger' | 'neutral';

type GoalCardGoal = GoalWithProgress & {
  is_system?: boolean;
  is_on_track?: boolean | null;
};

function getToneBadge(tone: Tone): string {
  if (tone === 'good') return 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200';
  if (tone === 'warning') return 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200';
  if (tone === 'danger') return 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200';
  return 'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200';
}

function GoalStatusBadge({ goal }: { goal: GoalCardGoal }) {
  if (goal.status === 'achieved') {
    return (
      <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', getToneBadge('good'))}>
        Достигнута ✓
      </span>
    );
  }

  if (!goal.deadline) {
    return (
      <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', getToneBadge('neutral'))}>
        В процессе
      </span>
    );
  }

  if (goal.is_on_track === true) {
    return (
      <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', getToneBadge('good'))}>
        На треке
      </span>
    );
  }

  if (goal.is_on_track === false) {
    return (
      <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', getToneBadge('warning'))}>
        Отстаёшь
      </span>
    );
  }

  return (
    <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', getToneBadge('neutral'))}>
      Нет данных
    </span>
  );
}

// ── Goal form modal ───────────────────────────────────────────────────────────

type GoalFormValues = {
  name: string;
  target_amount: string;
  deadline: string;
};

function GoalFormModal({
  initial,
  onClose,
  onSubmit,
  isSubmitting,
}: {
  initial?: GoalWithProgress | null;
  onClose: () => void;
  onSubmit: (values: GoalFormValues) => void;
  isSubmitting: boolean;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<GoalFormValues>({
    defaultValues: {
      name: initial?.name ?? '',
      target_amount: initial ? String(initial.target_amount) : '',
      deadline: initial?.deadline ?? '',
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md surface-panel p-6">
        <h2 className="mb-5 text-base font-semibold text-slate-950">
          {initial ? 'Редактировать цель' : 'Новая цель'}
        </h2>

        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div>
            <Label htmlFor="goal-name">Название</Label>
            <Input
              id="goal-name"
              className="h-9"
              placeholder="Например: MacBook Pro"
              {...register('name', { required: 'Укажи название' })}
            />
            {errors.name && <p className="mt-1 text-xs text-danger">{errors.name.message}</p>}
          </div>

          <div>
            <Label htmlFor="goal-amount">Целевая сумма, ₽</Label>
            <Input
              id="goal-amount"
              className="h-9"
              type="number"
              step="0.01"
              placeholder="0.00"
              {...register('target_amount', {
                required: 'Укажи сумму',
                validate: (v) => Number(v) > 0 || 'Сумма должна быть больше 0',
              })}
            />
            {errors.target_amount && (
              <p className="mt-1 text-xs text-danger">{errors.target_amount.message}</p>
            )}
          </div>

          <div>
            <Label htmlFor="goal-deadline">Дедлайн (необязательно)</Label>
            <Input id="goal-deadline" className="h-9" type="date" {...register('deadline')} />
          </div>

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

// ── Goal card ─────────────────────────────────────────────────────────────────

function GoalCard({
  goal,
  onEdit,
  onArchive,
}: {
  goal: GoalCardGoal;
  onEdit: (goal: GoalCardGoal) => void;
  onArchive: (goal: GoalCardGoal) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const isAchieved = goal.status === 'achieved';
  const isArchived = goal.status === 'archived';
  const isSystem = goal.is_system === true;

  return (
    <div
      className={cn(
        'surface-panel relative flex flex-col gap-3 p-5',
        isAchieved && 'ring-2 ring-amber-300',
        isArchived && 'opacity-60',
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-2">
          <p className="text-sm font-semibold leading-snug text-slate-900">{goal.name}</p>
          {isSystem ? (
            <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200">
              Системная цель
            </span>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {!isSystem ? <GoalStatusBadge goal={goal} /> : null}

          {!isSystem ? (
            <div className="relative">
              <button
                type="button"
                onClick={() => setMenuOpen((v) => !v)}
                className="flex size-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
              >
                <MoreHorizontal className="size-4" />
              </button>
              {menuOpen && (
                <>
                  {/* backdrop to close on outside click */}
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setMenuOpen(false)}
                  />
                  <div className="absolute right-0 top-8 z-20 min-w-[160px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-md">
                    {!isArchived && (
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
                        onClick={() => { setMenuOpen(false); onEdit(goal); }}
                      >
                        <Pencil className="size-3.5" /> Редактировать
                      </button>
                    )}
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50"
                      onClick={() => { setMenuOpen(false); onArchive(goal); }}
                    >
                      <Archive className="size-3.5" /> Архивировать
                    </button>
                  </div>
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>

      {/* Progress bar */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className={cn('text-xl font-bold tabular-nums', isAchieved ? 'text-amber-500' : 'text-slate-900')}>
            {goal.percent.toFixed(0)}%
          </span>
          {isAchieved && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
              🎉 Цель достигнута!
            </span>
          )}
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div
            className={cn(
              'h-full rounded-full transition-all duration-500',
              isAchieved ? 'bg-amber-400' : 'bg-emerald-500',
            )}
            style={{ width: `${Math.min(goal.percent, 100)}%` }}
          />
        </div>
      </div>

      {/* Amounts */}
      <div className="space-y-1">
        <p className="text-xs text-slate-500">
          <span className="font-medium text-slate-700">{formatMoney(goal.saved)}</span>
          {' '}из{' '}
          <span className="font-medium text-slate-700">{formatMoney(goal.target_amount)}</span>
        </p>

        {goal.deadline && (
          <p className="text-xs text-slate-500">
            До дедлайна:{' '}
            <span className="font-medium text-slate-700">
              {(() => {
                const now = new Date();
                const dl = new Date(goal.deadline);
                const months =
                  (dl.getFullYear() - now.getFullYear()) * 12 + (dl.getMonth() - now.getMonth());
                return months > 0 ? monthsLabel(months) : dl.toLocaleDateString('ru-RU');
              })()}
            </span>
          </p>
        )}

        {goal.monthly_needed != null && goal.monthly_needed > 0 && (
          <p className="text-xs text-slate-500">
            Откладывать:{' '}
            <span className="font-medium text-emerald-600">{formatMoney(goal.monthly_needed)}/мес</span>
          </p>
        )}
      </div>

      {/* Archive button for achieved goals */}
      {isAchieved && (
        <button
          type="button"
          onClick={() => onArchive(goal)}
          className="mt-1 flex items-center gap-1.5 self-start rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 transition hover:bg-amber-100"
        >
          <Archive className="size-3" /> В архив
        </button>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

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

  function handleCreateSubmit(values: GoalFormValues) {
    const payload: CreateGoalPayload = {
      name: values.name.trim(),
      target_amount: Number(values.target_amount),
      deadline: values.deadline || null,
    };
    createMutation.mutate(payload);
  }

  function handleEditSubmit(values: GoalFormValues) {
    if (!editingGoal) return;
    updateMutation.mutate({
      id: editingGoal.id,
      payload: {
        name: values.name.trim(),
        target_amount: Number(values.target_amount),
        deadline: values.deadline || null,
      },
    });
  }

  const visibleGoals = goals?.filter((g) => g.status !== 'archived') ?? [];
  const archivedGoals = goals?.filter((g) => g.status === 'archived') ?? [];

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-950">Мои цели</h1>
          <p className="mt-0.5 text-sm text-slate-500">Финансовые цели и прогресс их достижения</p>
        </div>
        <Button onClick={() => setShowModal(true)} className="shrink-0">
          <Plus className="mr-1.5 size-4" />
          Новая цель
        </Button>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="surface-panel p-5 space-y-3">
              <div className="h-4 w-40 animate-pulse rounded bg-slate-100" />
              <div className="h-2 w-full animate-pulse rounded-full bg-slate-100" />
              <div className="h-3 w-32 animate-pulse rounded bg-slate-100" />
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!isLoading && visibleGoals.length === 0 && (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/60 py-20 text-center">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-slate-100">
            <Target className="size-7 text-slate-400" />
          </div>
          <p className="mt-4 text-base font-medium text-slate-600">У вас пока нет целей</p>
          <p className="mt-1 text-sm text-slate-400">Поставьте финансовую цель и отслеживайте прогресс</p>
          <Button className="mt-5" onClick={() => setShowModal(true)}>
            <Plus className="mr-1.5 size-4" />
            Создать первую цель
          </Button>
        </div>
      )}

      {/* Active + achieved goals grid */}
      {!isLoading && visibleGoals.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {visibleGoals.map((goal) => (
            <GoalCard
              key={goal.id}
              goal={goal}
              onEdit={setEditingGoal}
              onArchive={(g) => archiveMutation.mutate(g.id)}
            />
          ))}
        </div>
      )}

      {/* Archived section */}
      {!isLoading && archivedGoals.length > 0 && (
        <details className="group">
          <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium text-slate-400 select-none">
            <Archive className="size-4" />
            Архив ({archivedGoals.length})
          </summary>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {archivedGoals.map((goal) => (
              <GoalCard
                key={goal.id}
                goal={goal}
                onEdit={setEditingGoal}
                onArchive={(g) => archiveMutation.mutate(g.id)}
              />
            ))}
          </div>
        </details>
      )}

      {/* Create modal */}
      {showModal && (
        <GoalFormModal
          onClose={() => setShowModal(false)}
          onSubmit={handleCreateSubmit}
          isSubmitting={createMutation.isPending}
        />
      )}

      {/* Edit modal */}
      {editingGoal && (
        <GoalFormModal
          initial={editingGoal}
          onClose={() => setEditingGoal(null)}
          onSubmit={handleEditSubmit}
          isSubmitting={updateMutation.isPending}
        />
      )}
    </div>
  );
}
