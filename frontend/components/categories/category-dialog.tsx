'use client';

import { CategoryForm } from '@/components/categories/category-form';
import { Dialog } from '@/components/ui/dialog';
import type { Category, CreateCategoryPayload } from '@/types/category';

export function CategoryDialog({
  open,
  mode,
  category,
  initialValues,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  open: boolean;
  mode: 'create' | 'edit';
  category?: Category | null;
  initialValues?: Partial<CreateCategoryPayload> | null;
  isSubmitting?: boolean;
  onClose: () => void;
  onSubmit: (values: CreateCategoryPayload) => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={mode === 'create' ? 'Новая категория' : 'Редактировать категорию'}
      description={mode === 'create' ? 'Создай категорию, чтобы удобно группировать транзакции.' : 'Обнови параметры категории.'}
    >
      <CategoryForm
        initialData={category}
        initialValues={initialValues}
        isSubmitting={isSubmitting}
        onSubmit={onSubmit}
        onCancel={onClose}
      />
    </Dialog>
  );
}
