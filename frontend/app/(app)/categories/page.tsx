"use client";

import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownCircle, ArrowUpCircle, PlusCircle, Search, Tags } from 'lucide-react';
import { toast } from 'sonner';
import { CategoryDialog } from '@/components/categories/category-dialog';
import { CategoriesList } from '@/components/categories/categories-list';
import { PageShell } from '@/components/layout/page-shell';
import { ErrorState, EmptyState, LoadingState } from '@/components/states/page-state';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { createCategory, deleteCategory, getCategories, updateCategory } from '@/lib/api/categories';
import type { Category, CategoryKind, CategoryPriority, CreateCategoryPayload } from '@/types/category';
import { StatCard } from '@/components/shared/stat-card';
import { useDelayedDelete } from '@/hooks/use-delayed-delete';

const allTypeOptions: { value: CategoryPriority; label: string }[] = [
  { value: 'expense_essential', label: 'Основной' },
  { value: 'expense_secondary', label: 'Второстепенный' },
  { value: 'expense_target', label: 'Целевой' },
  { value: 'income_active', label: 'Активный' },
  { value: 'income_passive', label: 'Пассивный' },
];

const expenseTypeOptions = allTypeOptions.filter((item) => item.value.startsWith('expense_'));
const incomeTypeOptions = allTypeOptions.filter((item) => item.value.startsWith('income_'));

export default function CategoriesPage() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingCategory, setEditingCategory] = useState<Category | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const delayedDelete = useDelayedDelete();

  const [search, setSearch] = useState('');
  const [kindFilter, setKindFilter] = useState<'all' | CategoryKind>('all');
  const [priorityFilter, setPriorityFilter] = useState<'all' | CategoryPriority>('all');

  const priorityOptions = useMemo(() => {
    if (kindFilter === 'expense') return expenseTypeOptions;
    if (kindFilter === 'income') return incomeTypeOptions;
    return allTypeOptions;
  }, [kindFilter]);

  const categoriesQuery = useQuery({
    queryKey: ['categories', { search, kindFilter, priorityFilter }],
    queryFn: () =>
      getCategories({
        search,
        kind: kindFilter,
        priority: priorityFilter,
      }),
  });

  const createMutation = useMutation({
    mutationFn: createCategory,
    onSuccess: () => {
      toast.success('Категория создана');
      setDialogOpen(false);
      queryClient.invalidateQueries({ queryKey: ['categories'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось создать категорию'),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: CreateCategoryPayload }) => updateCategory(id, payload),
    onSuccess: () => {
      toast.success('Категория обновлена');
      setDialogOpen(false);
      setEditingCategory(null);
      queryClient.invalidateQueries({ queryKey: ['categories'] });
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось обновить категорию'),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteCategory,
    onSuccess: () => {
      toast.success('Категория удалена');
      queryClient.invalidateQueries({ queryKey: ['categories'] });
      setDeletingId(null);
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Не удалось удалить категорию');
      setDeletingId(null);
    },
  });

  const stats = useMemo(() => {
    const list = categoriesQuery.data ?? [];
    return {
      total: list.length,
      income: list.filter((item) => item.kind === 'income').length,
      expense: list.filter((item) => item.kind === 'expense').length,
    };
  }, [categoriesQuery.data]);

  function openCreateDialog() {
    setEditingCategory(null);
    setDialogOpen(true);
  }

  function openEditDialog(category: Category) {
    setEditingCategory(category);
    setDialogOpen(true);
  }

  function handleDialogSubmit(values: CreateCategoryPayload) {
    if (editingCategory) {
      updateMutation.mutate({ id: editingCategory.id, payload: values });
      return;
    }
    createMutation.mutate(values);
  }

  function handleDelete(category: Category) {
    delayedDelete.scheduleDelete(category.id, () => {
      setDeletingId(category.id);
      deleteMutation.mutate(category.id);
    });
  }

  function handleKindFilterChange(value: 'all' | CategoryKind) {
    setKindFilter(value);
    if (value === 'expense' && priorityFilter !== 'all' && !String(priorityFilter).startsWith('expense_')) setPriorityFilter('all');
    if (value === 'income' && priorityFilter !== 'all' && !String(priorityFilter).startsWith('income_')) setPriorityFilter('all');
  }

  return (
    <PageShell
      title="Категории"
      description="Настрой справочник доходов и расходов в едином стиле: иконки назначаются автоматически, а цвет для каждой категории система подбирает сама."
      actions={
        <Button onClick={openCreateDialog}>
          <PlusCircle className="size-4" />
          Добавить категорию
        </Button>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <StatCard label="Всего категорий" value={stats.total} hint="Текущий объём справочника" icon={<Tags className="size-5" />} />
        <StatCard label="Доходные" value={stats.income} hint="Активные и пассивные доходы" icon={<ArrowUpCircle className="size-5" />} />
        <StatCard label="Расходные" value={stats.expense} hint="Основные, второстепенные и целевые" icon={<ArrowDownCircle className="size-5" />} />
      </div>

      <Card className="p-4 lg:p-5">
        <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr_1fr]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <Input className="pl-9" placeholder="Быстрый поиск категории" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>

          <Select value={kindFilter} onChange={(event) => handleKindFilterChange(event.target.value as 'all' | CategoryKind)}>
            <option value="all">Все виды</option>
            <option value="expense">Только расходы</option>
            <option value="income">Только доходы</option>
          </Select>

          <Select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value as 'all' | CategoryPriority)}>
            <option value="all">Все типы</option>
            {priorityOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Select>
        </div>
      </Card>

      {categoriesQuery.isLoading ? <LoadingState title="Загружаем категории..." description="Подготавливаем справочник для фильтрации и выбора." /> : null}

      {categoriesQuery.isError ? <ErrorState title="Не удалось загрузить категории" description="Проверь доступность backend API и повтори попытку." /> : null}

      {!categoriesQuery.isLoading && !categoriesQuery.isError && (categoriesQuery.data?.length ?? 0) === 0 ? (
        <EmptyState title="Категории не найдены" description="Измени фильтры или создай новую категорию." />
      ) : null}

      {!categoriesQuery.isLoading && !categoriesQuery.isError && (categoriesQuery.data?.length ?? 0) > 0 ? (
        <CategoriesList
          categories={categoriesQuery.data ?? []}
          onEdit={openEditDialog}
          onDelete={handleDelete}
          onCancelDelete={delayedDelete.cancelDelete}
          deletingId={deletingId}
          pendingDeleteIds={Object.keys(delayedDelete.pendingIds).map(Number)}
        />
      ) : null}

      <CategoryDialog
        open={dialogOpen}
        mode={editingCategory ? 'edit' : 'create'}
        category={editingCategory}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        onClose={() => {
          setDialogOpen(false);
          setEditingCategory(null);
        }}
        onSubmit={handleDialogSubmit}
      />
    </PageShell>
  );
}
