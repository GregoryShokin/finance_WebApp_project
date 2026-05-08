from __future__ import annotations

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.models.brand_identifier import BrandIdentifier


class BrandIdentifierRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
    ) -> BrandIdentifier | None:
        return (
            self.db.query(BrandIdentifier)
            .filter(
                BrandIdentifier.user_id == user_id,
                BrandIdentifier.identifier_kind == identifier_kind,
                BrandIdentifier.identifier_value == identifier_value,
            )
            .first()
        )

    def list_by_pairs(
        self,
        *,
        user_id: int,
        pairs: list[tuple[str, str]],
    ) -> list[BrandIdentifier]:
        if not pairs:
            return []
        return (
            self.db.query(BrandIdentifier)
            .filter(
                BrandIdentifier.user_id == user_id,
                tuple_(
                    BrandIdentifier.identifier_kind,
                    BrandIdentifier.identifier_value,
                ).in_([(k, v) for k, v in pairs]),
            )
            .all()
        )

    def list_by_brand(
        self, *, user_id: int, brand_id: int,
    ) -> list[BrandIdentifier]:
        return (
            self.db.query(BrandIdentifier)
            .filter(
                BrandIdentifier.user_id == user_id,
                BrandIdentifier.brand_id == brand_id,
            )
            .all()
        )

    def upsert(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
        brand_id: int,
    ) -> tuple[BrandIdentifier, bool]:
        binding = self.get(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
        )
        is_new = binding is None
        if binding is None:
            binding = BrandIdentifier(
                user_id=user_id,
                identifier_kind=identifier_kind,
                identifier_value=identifier_value,
                brand_id=brand_id,
                confirms=1,
            )
            self.db.add(binding)
        else:
            binding.brand_id = brand_id
            binding.confirms = (binding.confirms or 0) + 1
        self.db.flush()
        return binding, is_new

    def delete(self, *, binding: BrandIdentifier) -> None:
        self.db.delete(binding)
        self.db.flush()
