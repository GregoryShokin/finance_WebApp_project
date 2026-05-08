from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.brand_fingerprint import BrandFingerprint
from app.repositories.brand_fingerprint_repository import (
    BrandFingerprintRepository,
)

logger = logging.getLogger(__name__)


class BrandFingerprintService:
    """Successor to `CounterpartyFingerprintService` for the merged-Brand
    world (Phase C step 2+).

    Same contract — fingerprint → entity binding, user-scoped,
    upsert-on-rebind. The only change is the entity is now Brand
    (sometimes global). Bindings remain user-scoped so a global brand
    accumulates per-user fingerprints without leaking across users.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = BrandFingerprintRepository(db)
        self._cache: dict[tuple[int, str], int] = {}

    def resolve(self, *, user_id: int, fingerprint: str) -> int | None:
        if not fingerprint:
            return None
        key = (user_id, fingerprint)
        if key in self._cache:
            return self._cache[key]
        binding = self.repo.get_by_fingerprint(
            user_id=user_id, fingerprint=fingerprint,
        )
        brand_id = binding.brand_id if binding is not None else None
        if brand_id is not None:
            self._cache[key] = brand_id
        return brand_id

    def resolve_many(
        self, *, user_id: int, fingerprints: Iterable[str],
    ) -> dict[str, int]:
        unique_fps = [fp for fp in set(fingerprints) if fp]
        if not unique_fps:
            return {}
        bindings = self.repo.list_by_fingerprints(
            user_id=user_id, fingerprints=unique_fps,
        )
        out: dict[str, int] = {}
        for b in bindings:
            out[b.fingerprint] = b.brand_id
            self._cache[(user_id, b.fingerprint)] = b.brand_id
        return out

    def bind(
        self, *, user_id: int, fingerprint: str, brand_id: int,
    ) -> BrandFingerprint:
        if not fingerprint:
            raise ValueError("fingerprint must be non-empty")
        binding, _is_new = self.repo.upsert(
            user_id=user_id, fingerprint=fingerprint, brand_id=brand_id,
        )
        self._cache[(user_id, fingerprint)] = brand_id
        return binding

    def bind_many(
        self,
        *,
        user_id: int,
        fingerprints: Iterable[str],
        brand_id: int,
    ) -> int:
        seen: set[str] = set()
        count = 0
        for fp in fingerprints:
            if not fp or fp in seen:
                continue
            seen.add(fp)
            try:
                self.bind(
                    user_id=user_id, fingerprint=fp, brand_id=brand_id,
                )
                count += 1
            except Exception as exc:  # noqa: BLE001 — never block bulk-apply on binding errors
                logger.warning(
                    "brand fingerprint binding failed user=%s fp=%s brand=%s: %s",
                    user_id, fp, brand_id, exc,
                )
        return count

    def unbind(self, *, user_id: int, fingerprint: str) -> bool:
        binding = self.repo.get_by_fingerprint(
            user_id=user_id, fingerprint=fingerprint,
        )
        if binding is None:
            return False
        self.repo.delete(binding=binding)
        self._cache.pop((user_id, fingerprint), None)
        return True
