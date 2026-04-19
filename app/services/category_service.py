
from app.models.category import Category
from app.repositories.category_repository import CategoryRepository
from app.services.category_defaults import (
    DEFAULT_CATEGORIES,
    SYSTEM_CATEGORIES,
    resolve_category_icon_name,
    resolve_next_category_color,
)


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

    def create_category(self, *, user_id: int, name: str, kind: str, priority: str, regularity: str = "regular", color: str | None = None, icon_name: str | None = None, is_system: bool = False) -> Category:
        validate_category_priority(kind, priority)
        selected_color = color or resolve_next_category_color(self.repo.list_used_colors(user_id=user_id))
        selected_icon_name = (icon_name or resolve_category_icon_name(name)).strip() or 'tag'
        return self.repo.create(
            user_id=user_id,
            name=name,
            kind=kind,
            priority=priority,
            regularity=regularity,
            color=selected_color,
            icon_name=selected_icon_name,
            is_system=is_system,
        )

    def update_category(self, *, user_id: int, category_id: int, updates: dict) -> Category:
        category = self.repo.get_by_id(category_id=category_id, user_id=user_id)
        if not category:
            raise CategoryNotFoundError("Category not found")

        if category.is_system:
            raise CategoryValidationError("Системную категорию нельзя изменять.")

        effective_kind = updates.get('kind', category.kind)
        effective_priority = updates.get('priority', category.priority)
        effective_name = updates.get('name', category.name)
        validate_category_priority(effective_kind, effective_priority)

        sanitized_updates = dict(updates)
        sanitized_updates.pop('color', None)
        sanitized_updates['icon_name'] = resolve_category_icon_name(effective_name)
        if not category.color:
            sanitized_updates['color'] = resolve_next_category_color(self.repo.list_used_colors(user_id=user_id))

        return self.repo.update(category, **sanitized_updates)

    def delete_category(self, *, user_id: int, category_id: int) -> None:
        category = self.repo.get_by_id(category_id=category_id, user_id=user_id)
        if not category:
            raise CategoryNotFoundError("Category not found")
        if category.is_system:
            raise CategoryValidationError("Системную категорию нельзя удалять.")
        self.repo.delete(category)


    def ensure_system_categories(self, *, user_id: int) -> list[Category]:
        created: list[Category] = []
        for item in SYSTEM_CATEGORIES:
            existing_count = self.repo.count_by_identity(
                user_id=user_id,
                name=item.name,
                kind=item.kind,
                priority=item.priority,
            )
            if existing_count:
                continue
            created.append(
                self.create_category(
                    user_id=user_id,
                    name=item.name,
                    kind=item.kind,
                    priority=item.priority,
                    regularity=item.regularity,
                    icon_name=item.icon_name,
                    color="#94a3b8",
                    is_system=True,
                )
            )
        return created

    def ensure_default_categories(self, *, user_id: int) -> list[Category]:
        self.ensure_system_categories(user_id=user_id)
        created_categories: list[Category] = []
        for item in DEFAULT_CATEGORIES:
            existing_count = self.repo.count_by_identity(
                user_id=user_id,
                name=item.name,
                kind=item.kind,
                priority=item.priority,
            )
            if existing_count:
                continue
            created_categories.append(
                self.create_category(
                    user_id=user_id,
                    name=item.name,
                    kind=item.kind,
                    priority=item.priority,
                    icon_name=item.icon_name,
                    is_system=False,
                )
            )
        return created_categories
