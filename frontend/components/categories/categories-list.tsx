import { CategoryCard } from '@/components/categories/category-card';
import type { Category } from '@/types/category';

export function CategoriesList({
  categories,
  onEdit,
  onDelete,
  onCancelDelete,
  deletingId,
  pendingDeleteIds,
}: {
  categories: Category[];
  onEdit: (category: Category) => void;
  onDelete: (category: Category) => void;
  onCancelDelete: (categoryId: number) => void;
  deletingId?: number | null;
  pendingDeleteIds?: number[];
}) {
  const pendingSet = new Set(pendingDeleteIds ?? []);

  return (
    <div className="grid gap-4">
      {categories.map((category) => (
        <CategoryCard
          key={category.id}
          category={category}
          onEdit={onEdit}
          onDelete={onDelete}
          onCancelDelete={onCancelDelete}
          isDeletePending={pendingSet.has(category.id)}
          isDeleting={deletingId === category.id}
        />
      ))}
    </div>
  );
}
