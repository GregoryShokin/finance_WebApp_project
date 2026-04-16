from __future__ import annotations


from sqlalchemy.orm import Session

from sqlalchemy import func

from app.models.category import Category


class CategoryRepository:
    def __init__(self, db: Session):
        self.db = db

    def list(
        self,
        *,
        user_id: int,
        kind: str | None = None,
        priority: str | None = None,
        search: str | None = None,
    ) -> list[Category]:
        query = self.db.query(Category).filter(Category.user_id == user_id)

        if kind:
            query = query.filter(Category.kind == kind)
        if priority:
            query = query.filter(Category.priority == priority)
        if search:
            query = query.filter(Category.name.ilike(f"%{search.strip()}%"))

        return query.order_by(Category.name.asc(), Category.id.asc()).all()

    def get_by_id(self, *, category_id: int, user_id: int) -> Category | None:
        return (
            self.db.query(Category)
            .filter(Category.id == category_id, Category.user_id == user_id)
            .first()
        )

    def create(
        self,
        *,
        user_id: int,
        name: str,
        kind: str,
        priority: str,
        regularity: str = "regular",
        color: str | None,
        icon_name: str,
        is_system: bool,
    ) -> Category:
        category = Category(
            user_id=user_id,
            name=name,
            kind=kind,
            priority=priority,
            regularity=regularity,
            color=color,
            icon_name=icon_name,
            is_system=is_system,
        )
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def update(self, category: Category, **updates) -> Category:
        for key, value in updates.items():
            if value is not None:
                setattr(category, key, value)
        self.db.add(category)
        self.db.commit()
        self.db.refresh(category)
        return category

    def delete(self, category: Category) -> None:
        self.db.delete(category)
        self.db.commit()


    def list_used_colors(self, *, user_id: int) -> list[str]:
        return [
            color
            for (color,) in self.db.query(Category.color)
            .filter(Category.user_id == user_id, Category.color.isnot(None))
            .order_by(Category.id.asc())
            .all()
            if color
        ]

    def count_by_identity(self, *, user_id: int, name: str, kind: str, priority: str) -> int:
        return (
            self.db.query(func.count(Category.id))
            .filter(
                Category.user_id == user_id,
                Category.name == name,
                Category.kind == kind,
                Category.priority == priority,
            )
            .scalar()
            or 0
        )
