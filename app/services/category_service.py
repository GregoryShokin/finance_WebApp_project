
from app.models.category import Category
from app.repositories.category_repository import CategoryRepository


class CategoryNotFoundError(Exception):
    pass


class CategoryValidationError(Exception):
    pass


EXPENSE_PRIORITY_VALUES = {
    "expense_essential",
    "expense_secondary",
    "expense_target",
}
INCOME_PRIORITY_VALUES = {
    "income_active",
    "income_passive",
}


def validate_category_priority(kind: str, priority: str) -> None:
    if kind == "expense" and priority not in EXPENSE_PRIORITY_VALUES:
        raise CategoryValidationError("Для расходов доступны только типы: основной, второстепенный, целевой.")
    if kind == "income" and priority not in INCOME_PRIORITY_VALUES:
        raise CategoryValidationError("Для доходов доступны только типы: активный или пассивный.")


class CategoryService:
    def __init__(self, db):
        self.repo = CategoryRepository(db)

    def list_categories(self, *, user_id: int, kind: str | None = None, priority: str | None = None, search: str | None = None) -> list[Category]:
        return self.repo.list(user_id=user_id, kind=kind, priority=priority, search=search)

    def create_category(self, *, user_id: int, name: str, kind: str, priority: str, color: str | None, is_system: bool) -> Category:
        validate_category_priority(kind, priority)
        return self.repo.create(
            user_id=user_id,
            name=name,
            kind=kind,
            priority=priority,
            color=color,
            is_system=is_system,
        )

    def update_category(self, *, user_id: int, category_id: int, updates: dict) -> Category:
        category = self.repo.get_by_id(category_id=category_id, user_id=user_id)
        if not category:
            raise CategoryNotFoundError("Category not found")

        effective_kind = updates.get("kind", category.kind)
        effective_priority = updates.get("priority", category.priority)
        validate_category_priority(effective_kind, effective_priority)

        return self.repo.update(category, **updates)

    def delete_category(self, *, user_id: int, category_id: int) -> None:
        category = self.repo.get_by_id(category_id=category_id, user_id=user_id)
        if not category:
            raise CategoryNotFoundError("Category not found")
        self.repo.delete(category)
