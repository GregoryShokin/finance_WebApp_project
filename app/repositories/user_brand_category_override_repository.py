from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user_brand_category_override import UserBrandCategoryOverride


class UserBrandCategoryOverrideRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self, *, user_id: int, brand_id: int,
    ) -> UserBrandCategoryOverride | None:
        return (
            self.db.query(UserBrandCategoryOverride)
            .filter(
                UserBrandCategoryOverride.user_id == user_id,
                UserBrandCategoryOverride.brand_id == brand_id,
            )
            .first()
        )

    def upsert(
        self, *, user_id: int, brand_id: int, category_id: int,
    ) -> tuple[UserBrandCategoryOverride, bool]:
        """Replace any prior override; returns (row, is_new)."""
        existing = self.get(user_id=user_id, brand_id=brand_id)
        if existing is not None:
            existing.category_id = category_id
            self.db.add(existing)
            self.db.flush()
            return existing, False
        row = UserBrandCategoryOverride(
            user_id=user_id, brand_id=brand_id, category_id=category_id,
        )
        self.db.add(row)
        self.db.flush()
        return row, True

    def delete(self, *, user_id: int, brand_id: int) -> bool:
        existing = self.get(user_id=user_id, brand_id=brand_id)
        if existing is None:
            return False
        self.db.delete(existing)
        self.db.flush()
        return True
