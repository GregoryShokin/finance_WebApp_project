from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.counterparty_identifier import CounterpartyIdentifier
from app.repositories.counterparty_identifier_repository import (
    CounterpartyIdentifierRepository,
)

logger = logging.getLogger(__name__)


# Identifier kinds that make sense as cross-account bindings. A phone / contract
# / IBAN uniquely points at one person or organisation regardless of which of
# the user's accounts initiated the transfer. `card` is here too — a masked PAN
# is a stable property of the recipient. `person_hash` is intentionally NOT
# supported: it's derived from a name inside a skeleton, which can collide
# across different people, so fingerprint-level binding is safer there.
SUPPORTED_IDENTIFIER_KINDS: frozenset[str] = frozenset({
    "phone", "contract", "iban", "card",
})


class CounterpartyIdentifierService:
    """Cross-account identifier → counterparty binding.

    Purpose: fix the case where a user binds "+79281935935 → Арендодатель" on a
    Tinkoff credit card statement and then imports a Tinkoff debit statement
    that carries the same phone number. The v2 fingerprint bakes `account_id`
    and `bank` into its payload, so the CounterpartyFingerprint binding made
    on one statement doesn't resolve on another. This service stores a
    narrower binding keyed only on the identifier itself.

    Resolution order at cluster build time:
      1. Identifier binding — if the cluster has a supported identifier_kind.
      2. Fingerprint binding — fallback for skeleton/brand clusters without
         an identifier (e.g. purchases at "KOFEMOLOKO").

    Bindings are created implicitly during bulk-apply when the user picks a
    counterparty for a cluster that carries an identifier.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = CounterpartyIdentifierRepository(db)
        self._cache: dict[tuple[int, str, str], int] = {}

    def resolve(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
    ) -> int | None:
        """Return counterparty_id for this identifier, or None if unbound."""
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
        cp_id = binding.counterparty_id if binding is not None else None
        if cp_id is not None:
            self._cache[key] = cp_id
        return cp_id

    def resolve_many(
        self,
        *,
        user_id: int,
        pairs: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], int]:
        """Batch-resolve a collection of (kind, value) pairs.

        Unsupported kinds and empty values are silently dropped. The returned
        mapping covers only pairs that have a binding — callers should treat
        missing keys as "unbound".
        """
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
            out[key] = b.counterparty_id
            self._cache[(user_id, b.identifier_kind, b.identifier_value)] = b.counterparty_id
        return out

    def bind(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
        counterparty_id: int,
    ) -> CounterpartyIdentifier | None:
        """Create or strengthen an identifier→counterparty binding.

        No-op (returns None) if identifier_kind is not in the supported set —
        bulk-apply calls this indiscriminately and we don't want to raise for
        clusters that lack a meaningful cross-account identifier.
        """
        if not identifier_value or identifier_kind not in SUPPORTED_IDENTIFIER_KINDS:
            return None
        binding, _is_new = self.repo.upsert(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
            counterparty_id=counterparty_id,
        )
        self._cache[(user_id, identifier_kind, identifier_value)] = counterparty_id
        return binding

    def bind_many(
        self,
        *,
        user_id: int,
        pairs: Iterable[tuple[str, str]],
        counterparty_id: int,
    ) -> int:
        """Bind every (kind, value) pair to the same counterparty.

        Called from bulk_apply_cluster alongside `CounterpartyFingerprintService.bind_many`
        — the identifier pairs come from cluster `identifier_key` + `identifier_value`,
        so a cluster with one phone creates one identifier binding, and future
        imports of that phone on any account resolve immediately.

        Returns the count of bindings created or strengthened (ignoring
        unsupported kinds and errors).
        """
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
                    counterparty_id=counterparty_id,
                ) is not None:
                    count += 1
            except Exception as exc:  # noqa: BLE001 — never block bulk-apply on binding errors
                logger.warning(
                    "counterparty identifier binding failed user=%s %s=%s cp=%s: %s",
                    user_id, kind, value, counterparty_id, exc,
                )
        return count

    def unbind(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
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
