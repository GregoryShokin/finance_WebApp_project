from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.brand_fingerprint import BrandFingerprint


class BrandFingerprintRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_fingerprint(
        self, *, user_id: int, fingerprint: str
    ) -> BrandFingerprint | None:
        return (
            self.db.query(BrandFingerprint)
            .filter(
                BrandFingerprint.user_id == user_id,
                BrandFingerprint.fingerprint == fingerprint,
            )
            .first()
        )

    def list_by_brand(
        self, *, user_id: int, brand_id: int
    ) -> list[BrandFingerprint]:
        return (
            self.db.query(BrandFingerprint)
            .filter(
                BrandFingerprint.user_id == user_id,
                BrandFingerprint.brand_id == brand_id,
            )
            .all()
        )

    def list_by_fingerprints(
        self, *, user_id: int, fingerprints: list[str]
    ) -> list[BrandFingerprint]:
        if not fingerprints:
            return []
        return (
            self.db.query(BrandFingerprint)
            .filter(
                BrandFingerprint.user_id == user_id,
                BrandFingerprint.fingerprint.in_(fingerprints),
            )
            .all()
        )

    def upsert(
        self,
        *,
        user_id: int,
        fingerprint: str,
        brand_id: int,
    ) -> tuple[BrandFingerprint, bool]:
        binding = self.get_by_fingerprint(user_id=user_id, fingerprint=fingerprint)
        is_new = binding is None
        if binding is None:
            binding = BrandFingerprint(
                user_id=user_id,
                fingerprint=fingerprint,
                brand_id=brand_id,
                confirms=1,
            )
            self.db.add(binding)
        else:
            binding.brand_id = brand_id
            binding.confirms = (binding.confirms or 0) + 1
        self.db.flush()
        return binding, is_new

    def delete(self, *, binding: BrandFingerprint) -> None:
        self.db.delete(binding)
        self.db.flush()
