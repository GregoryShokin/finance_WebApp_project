'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Archive, Lock, MoreHorizontal, Pencil, Plus, Shield, Target } from 'lucide-react';
import { useForm } from 'react-hook-form';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { archiveGoal, createGoal, getGoals, updateGoal } from '@/lib/api/goals';
import { getCategories } from '@/lib/api/categories';
import { cn } from '@/lib/utils/cn';
import { formatMoney } from '@/lib/utils/format';
import type { CreateGoalPayload, GoalWithProgress } from '@/types/goal';

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

type GoalFormValues = {
  name: string;
  target_amount: string;
  deadline: string;
  category_id: string;
};

function GoalFormModal({ initial, onClose, onSubmit, isSubmitting }: { initial?: GoalWithProgress | null; onClose: () => void; onSubmit: (values: GoalFormValues) => void; isSubmitting: boolean; }) {
  const { data: categories } = useQuery({ queryKey: ['categories'], queryFn: () => getCategories({ kind: 'expense' }), staleTime: 1000 * 60 * 5 });
  const expenseCategories = categories ?? [];

  const { register, handleSubmit, formState: { errors } } = useForm<GoalFormValues>({
    defaultValues: {
      name: initial?.name ?? '',
      target_amount: initial ? String(initial.target_amount) : '',
      deadline: initial?.deadline ?? '',
      category_id: initial?.category_id ? String(initial.category_id) : '',
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md surface-panel p-6">
        <h2 className="mb-5 text-base font-semibold text-slate-950">{initial ? 'Редактировать цель' : 'Новая цель'}</h2>
        <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
          <div>
            <Label htmlFor="goal-name">Название</Label>
            <Input id="goal-name" className="h-9" placeholder="Например: MacBook Pro" {...register('name', { required: 'Укажи название' })} />
            {errors.name ? <p className="mt-1 text-xs text-danger">{errors.name.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="goal-amount">Целевая сумма, ₽</Label>
            <Input id="goal-amount" className="h-9" type="number" step="0.01" placeholder="0.00" {...register('target_amount', { required: 'Укажи сумму', validate: (v) => Number(v) > 0 || 'Сумма должна быть больше 0' })} />
            {errors.target_amount ? <p className="mt-1 text-xs text-danger">{errors.target_amount.message}</p> : null}
          </div>
          <div>
            <Label htmlFor="goal-deadline">Дедлайн (необязательно)</Label>
            <Input id="goal-deadline" className="h-9" type="date" {...register('deadline')} />
          </div>
          {expenseCategories.length > 0 && (
            <div>
              <Label htmlFor="goal-category">Категория расходов (необязательно)</Label>
              <select
                id="goal-category"
                className="mt-1 h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-400"
                {...register('category_id')}
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
          <div className="flex flex-col-reverse gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:justify-end">
            <Button type="button" variant="secondary" onClick={onClose}>Отмена</Button>
            <Button type="submit" disabled={isSubmitting}>{isSubmitting ? 'Сохраняем...' : initial ? 'Сохранить' : 'Создать'}</Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function GoalCard({ goal, onEdit, onArchive }: { goal: GoalWithProgress; onEdit: (goal: GoalWithProgress) => void; onArchive: (goal: GoalWithProgress) => void; }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const isAchieved = goal.status === 'achieved';
  const isArchived = goal.status === 'archived';
  const isSystem = goal.is_system;

  return (
    <div className={cn('surface-panel relative flex flex-col gap-3 p-5', isAchieved && 'ring-2 ring-amber-300', isArchived && 'opacity-60', isSystem && 'border border-sky-100 bg-sky-50/40')}>
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-2">
          <p className="text-sm font-semibold leading-snug text-slate-900">{goal.name}</p>
          {isSystem ? <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700"><Shield className="size-3.5" />Системная цель</span> : null}
        </div>
        {!isSystem ? (
          <div className="relative shrink-0">
            <button type="button" onClick={() => setMenuOpen((v) => !v)} className="flex size-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-slate-100 hover:text-slate-600">
              <MoreHorizontal className="size-4" />
            </button>
            {menuOpen ? (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-8 z-20 min-w-[160px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-md">
                  {!isArchived ? <button type="button" className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50" onClick={() => { setMenuOpen(false); onEdit(goal); }}><Pencil className="size-3.5" /> Редактировать</button> : null}
                  <button type="button" className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-slate-700 hover:bg-slate-50" onClick={() => { setMenuOpen(false); onArchive(goal); }}><Archive className="size-3.5" /> Архивировать</button>
                </div>
              </>
            ) : null}
          </div>
        ) : <div className="flex size-7 items-center justify-center rounded-full bg-white text-sky-500"><Lock className="size-4" /></div>}
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <span className={cn('text-xl font-bold tabular-nums', isAchieved ? 'text-amber-500' : 'text-slate-900')}>{goal.percent.toFixed(0)}%</span>
          {isAchieved ? <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">Цель достигнута</span> : null}
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div className={cn('h-full rounded-full transition-all duration-500', isAchieved ? 'bg-amber-400' : 'bg-emerald-500')} style={{ width: `${Math.min(goal.percent, 100)}%` }} />
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-xs text-slate-500"><span className="font-medium text-slate-700">{formatMoney(goal.saved)}</span> из <span className="font-medium text-slate-700">{formatMoney(goal.target_amount)}</span></p>
        {goal.deadline ? <p className="text-xs text-slate-500">До дедлайна: <span className="font-medium text-slate-700">{(() => { const now = new Date(); const deadline = new Date(goal.deadline); const months = (deadline.getFullYear() - now.getFullYear()) * 12 + (deadline.getMonth() - now.getMonth()); return months > 0 ? monthsLabel(months) : deadline.toLocaleDateString('ru-RU'); })()}</span></p> : null}
        {goal.monthly_needed != null && goal.monthly_needed > 0 ? <p className="text-xs text-slate-500">Откладывать: <span className="font-medium text-emerald-600">{formatMoney(goal.monthly_needed)}/мес</span></p> : null}
      </div>

      {isSystem ? <div className="mt-1 rounded-2xl bg-white/80 px-3 py-2 text-xs text-slate-500">Эта цель поддерживается системой и автоматически пересчитывает рекомендуемый размер подушки.</div> : null}
    </div>
  );
}

export default function GoalsPage() {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [editingGoal, setEditingGoal] = useState<GoalWithProgress | null>(null);

  const { data: goals, isLoading } = useQuery({ queryKey: ['goals'], queryFn: getGoals });

  const createMutation = useMutation({ mutationFn: createGoal, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['goals'] }); setShowModal(false); } });
  const updateMutation = useMutation({ mutationFn: ({ id, payload }: { id: number; payload: Parameters<typeof updateGoal>[1] }) => updateGoal(id, payload), onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['goals'] }); setEditingGoal(null); } });
  const archiveMutation = useMutation({ mutationFn: archiveGoal, onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['goals'] }); } });

  function handleCreateSubmit(values: GoalFormValues) {
    const payload: CreateGoalPayload = {
      name: values.name.trim(),
      target_amount: Number(values.target_amount),
      deadline: values.deadline || null,
      category_id: values.category_id ? Number(values.category_id) : null,
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
        category_id: values.category_id ? Number(values.category_id) : null,
      },
    });
  }

  const visibleGoals = goals?.filter((goal) => goal.status !== 'archived') ?? [];
  const archivedGoals = goals?.filter((goal) => goal.status === 'archived') ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-950">Мои цели</h1>
          <p className="mt-0.5 text-sm text-slate-500">Финансовые цели и прогресс их достижения</p>
        </div>
        <Button onClick={() => setShowModal(true)} className="shrink-0"><Plus className="mr-1.5 size-4" />Новая цель</Button>
      </div>

      {isLoading ? <div className="grid gap-4 sm:grid-cols-2">{[1,2,3,4].map((i) => <div key={i} className="surface-panel space-y-3 p-5"><div className="h-4 w-40 animate-pulse rounded bg-slate-100" /><div className="h-2 w-full animate-pulse rounded-full bg-slate-100" /><div className="h-3 w-32 animate-pulse rounded bg-slate-100" /></div>)}</div> : null}

      {!isLoading && visibleGoals.length === 0 ? <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-white/60 py-20 text-center"><div className="flex size-14 items-center justify-center rounded-2xl bg-slate-100"><Target className="size-7 text-slate-400" /></div><p className="mt-4 text-base font-medium text-slate-600">У вас пока нет целей</p><p className="mt-1 text-sm text-slate-400">Поставьте финансовую цель и отслеживайте прогресс</p><Button className="mt-5" onClick={() => setShowModal(true)}><Plus className="mr-1.5 size-4" />Создать первую цель</Button></div> : null}

      {!isLoading && visibleGoals.length > 0 ? <div className="grid gap-4 sm:grid-cols-2">{visibleGoals.map((goal) => <GoalCard key={goal.id} goal={goal} onEdit={setEditingGoal} onArchive={(item) => archiveMutation.mutate(item.id)} />)}</div> : null}

      {!isLoading && archivedGoals.length > 0 ? <details className="group"><summary className="flex cursor-pointer items-center gap-2 select-none text-sm font-medium text-slate-400"><Archive className="size-4" />Архив ({archivedGoals.length})</summary><div className="mt-3 grid gap-4 sm:grid-cols-2">{archivedGoals.map((goal) => <GoalCard key={goal.id} goal={goal} onEdit={setEditingGoal} onArchive={(item) => archiveMutation.mutate(item.id)} />)}</div></details> : null}

      {showModal ? <GoalFormModal onClose={() => setShowModal(false)} onSubmit={handleCreateSubmit} isSubmitting={createMutation.isPending} /> : null}
      {editingGoal ? <GoalFormModal initial={editingGoal} onClose={() => setEditingGoal(null)} onSubmit={handleEditSubmit} isSubmitting={updateMutation.isPending} /> : null}
    </div>
  );
}