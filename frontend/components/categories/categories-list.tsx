import { CategoryCard } from '@/components/categories/category-card';
import type { Category } from '@/types/category';

export function CategoriesList({
  categories,
  onEdit,
  onDelete,
  deletingId,
}: {
  categories: Category[];
  onEdit: (category: Category) => void;
  onDelete: (category: Category) => void;
  deletingId?: number | null;
}) {
  return (
    <div className="grid gap-4">
      {categories.map((category) => (
        <CategoryCard
          key={category.id}
          category={category}
          onEdit={onEdit}
          onDelete={onDelete}
          isDeleting={deletingId === category.id}
        />
      ))}
    </div>
  );
}
