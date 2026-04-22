"use client";

import { Pencil, RotateCcw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { StatusBadge } from '@/components/shared/status-badge';
import { CategoryIcon } from '@/components/categories/category-icon';
import type { Category } from '@/types/category';

const kindMap = {
  income: 'Доход',
  expense: 'Расход',
} as const;

const priorityMap = {
  expense_essential: 'Основной',
  expense_secondary: 'Второстепенный',
  expense_target: 'Имущество',
  income_active: 'Активный',
  income_passive: 'Пассивный',
} as const;

export function CategoryCard({
  category,
  onEdit,
  onDelete,
  onCancelDelete,
  isDeletePending,
  isDeleting,
}: {
  category: Category;
  onEdit: (category: Category) => void;
  onDelete: (category: Category) => void;
  onCancelDelete: (categoryId: number) => void;
  isDeletePending?: boolean;
  isDeleting?: boolean;
}) {
  return (
    <Card className="p-5 lg:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
              <CategoryIcon iconName={category.icon_name} className="size-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <div
                  className="h-4 w-4 shrink-0 rounded-full border border-slate-300"
                  style={{ backgroundColor: category.color ?? '#94a3b8' }}
                  title={category.color ?? 'Без цвета'}
                />
                <h3 className="truncate text-base font-semibold text-slate-950">{category.name}</h3>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <StatusBadge tone={category.kind === 'income' ? 'income' : 'expense'}>{kindMap[category.kind]}</StatusBadge>
                <StatusBadge>{priorityMap[category.priority]}</StatusBadge>
                {category.is_system ? <StatusBadge tone="warning">Системная</StatusBadge> : null}
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 lg:justify-end">
          {category.is_system ? (
            <span className="text-xs text-slate-400" title="Системные категории нельзя изменить или удалить">
              Системная — только для чтения
            </span>
          ) : (
            <>
              <Button
                type="button"
                variant="secondary"
                size="icon"
                onClick={() => onEdit(category)}
                aria-label="Изменить категорию"
                title="Изменить"
              >
                <Pencil className="size-4" />
              </Button>
              {isDeletePending ? (
                <Button
                  type="button"
                  variant="secondary"
                  size="icon"
                  onClick={() => onCancelDelete(category.id)}
                  disabled={isDeleting}
                  aria-label={isDeleting ? 'Категория удаляется' : 'Отменить удаление категории'}
                  title={isDeleting ? 'Удаляем...' : 'Отменить удаление'}
                >
                  <RotateCcw className="size-4" />
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="danger"
                  size="icon"
                  onClick={() => onDelete(category)}
                  disabled={isDeleting}
                  aria-label={isDeleting ? 'Удаляем категорию' : 'Удалить категорию'}
                  title={isDeleting ? 'Удаляем...' : 'Удалить'}
                >
                  <Trash2 className="size-4" />
                </Button>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}
