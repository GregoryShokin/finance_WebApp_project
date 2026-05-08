from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.brand_identifier import BrandIdentifier
from app.repositories.brand_identifier_repository import (
    BrandIdentifierRepository,
)

logger = logging.getLogger(__name__)


# Same identifier-kind whitelist as the legacy CP service. `person_hash`
# stays excluded — it's derived from a name inside a skeleton and can
# collide across different people, so fingerprint binding is safer there.
SUPPORTED_IDENTIFIER_KINDS: frozenset[str] = frozenset({
    "phone", "contract", "iban", "card",
})


class BrandIdentifierService:
    """Successor to `CounterpartyIdentifierService` for the merged-Brand
    world (Phase C step 2+).

    Cross-account semantics unchanged: a phone / contract / IBAN / card
    is the same person/entity regardless of which account paid them, so
    a binding made on one statement resolves on the next. With Brand
    replacing Counterparty as the merchant entity, the FK now points at
    `brand_identifiers.brand_id`.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = BrandIdentifierRepository(db)
        self._cache: dict[tuple[int, str, str], int] = {}

    def resolve(
        self, *, user_id: int, identifier_kind: str, identifier_value: str,
    ) -> int | None:
        if not identifier_value or identifier_kind not in SUPPORTED_IDENTIFIER_KINDS:
            return None
        key = (user_id, identifier_kind, identifier_value)
        if key in self._cache:
            return self._cache[key]
        binding = self.repo.get(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
        )
        brand_id = binding.brand_id if binding is not None else None
        if brand_id is not None:
            self._cache[key] = brand_id
        return brand_id

    def resolve_many(
        self, *, user_id: int, pairs: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], int]:
        unique: set[tuple[str, str]] = set()
        for kind, value in pairs:
            if not value or kind not in SUPPORTED_IDENTIFIER_KINDS:
                continue
            unique.add((kind, value))
        if not unique:
            return {}
        bindings = self.repo.list_by_pairs(user_id=user_id, pairs=list(unique))
        out: dict[tuple[str, str], int] = {}
        for b in bindings:
            key = (b.identifier_kind, b.identifier_value)
            out[key] = b.brand_id
            self._cache[(user_id, b.identifier_kind, b.identifier_value)] = b.brand_id
        return out

    def bind(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
        brand_id: int,
    ) -> BrandIdentifier | None:
        if not identifier_value or identifier_kind not in SUPPORTED_IDENTIFIER_KINDS:
            return None
        binding, _is_new = self.repo.upsert(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
            brand_id=brand_id,
        )
        self._cache[(user_id, identifier_kind, identifier_value)] = brand_id
        return binding

    def bind_many(
        self,
        *,
        user_id: int,
        pairs: Iterable[tuple[str, str]],
        brand_id: int,
    ) -> int:
        seen: set[tuple[str, str]] = set()
        count = 0
        for kind, value in pairs:
            if not value or kind not in SUPPORTED_IDENTIFIER_KINDS:
                continue
            key = (kind, value)
            if key in seen:
                continue
            seen.add(key)
            try:
                if self.bind(
                    user_id=user_id,
                    identifier_kind=kind,
                    identifier_value=value,
                    brand_id=brand_id,
                ) is not None:
                    count += 1
            except Exception as exc:  # noqa: BLE001 — never block bulk-apply on binding errors
                logger.warning(
                    "brand identifier binding failed user=%s %s=%s brand=%s: %s",
                    user_id, kind, value, brand_id, exc,
                )
        return count

    def unbind(
        self, *, user_id: int, identifier_kind: str, identifier_value: str,
    ) -> bool:
        binding = self.repo.get(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
        )
        if binding is None:
            return False
        self.repo.delete(binding=binding)
        self._cache.pop((user_id, identifier_kind, identifier_value), None)
        return True
