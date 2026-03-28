'use client';

import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import type { Category, CategoryKind, CategoryPriority, CreateCategoryPayload } from '@/types/category';

type CategoryFormValues = {
  name: string;
  kind: CategoryKind;
  priority: CategoryPriority;
};

const defaultValues: CategoryFormValues = {
  name: '',
  kind: 'expense',
  priority: 'expense_essential',
};

const expenseOptions: { value: CategoryPriority; label: string }[] = [
  { value: 'expense_essential', label: 'Основной' },
  { value: 'expense_secondary', label: 'Второстепенный' },
  { value: 'expense_target', label: 'Целевой' },
];

const incomeOptions: { value: CategoryPriority; label: string }[] = [
  { value: 'income_active', label: 'Активный' },
  { value: 'income_passive', label: 'Пассивный' },
];

export function CategoryForm({
  initialData,
  initialValues,
  isSubmitting,
  onSubmit,
  onCancel,
}: {
  initialData?: Category | null;
  initialValues?: Partial<CreateCategoryPayload> | null;
  isSubmitting?: boolean;
  onSubmit: (values: CreateCategoryPayload) => void;
  onCancel: () => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    watch,
    setValue,
    formState: { errors },
  } = useForm<CategoryFormValues>({
    defaultValues,
  });

  const selectedKind = watch('kind');
  const selectedPriority = watch('priority');

  const priorityOptions = useMemo(
    () => (selectedKind === 'income' ? incomeOptions : expenseOptions),
    [selectedKind],
  );

  useEffect(() => {
    if (selectedKind === 'expense' && !expenseOptions.some((item) => item.value === selectedPriority)) {
      setValue('priority', 'expense_essential');
    }
    if (selectedKind === 'income' && !incomeOptions.some((item) => item.value === selectedPriority)) {
      setValue('priority', 'income_active');
    }
  }, [selectedKind, selectedPriority, setValue]);

  useEffect(() => {
    if (initialData) {
      reset({
        name: initialData.name,
        kind: initialData.kind,
        priority: initialData.priority,
      });
      return;
    }

    reset({
      ...defaultValues,
      name: initialValues?.name ?? '',
      kind: initialValues?.kind ?? 'expense',
      priority:
        initialValues?.priority ??
        (initialValues?.kind === 'income' ? 'income_active' : 'expense_essential'),
    });
  }, [initialData, initialValues, reset]);

  return (
    <form
      className="space-y-4"
      onSubmit={handleSubmit((values) =>
        onSubmit({
          name: values.name,
          kind: values.kind,
          priority: values.priority,
        }),
      )}
    >
      <div>
        <Label htmlFor="category-name">Название категории</Label>
        <Input
          id="category-name"
          placeholder="Например, Продукты"
          {...register('name', {
            required: 'Укажи название категории',
            minLength: { value: 1, message: 'Название не должно быть пустым' },
          })}
        />
        {errors.name ? <p className="mt-1 text-sm text-danger">{errors.name.message}</p> : null}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="category-kind">Вид</Label>
          <Select id="category-kind" {...register('kind', { required: true })}>
            <option value="expense">Расход</option>
            <option value="income">Доход</option>
          </Select>
        </div>

        <div>
          <Label htmlFor="category-priority">Тип</Label>
          <Select id="category-priority" {...register('priority', { required: true })}>
            {priorityOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </Select>
        </div>
      </div>


      <div className="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Отмена
        </Button>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Сохраняем...' : initialData ? 'Сохранить изменения' : 'Создать категорию'}
        </Button>
      </div>
    </form>
  );
}
