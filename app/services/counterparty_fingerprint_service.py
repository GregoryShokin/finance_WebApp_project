from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.counterparty_fingerprint import CounterpartyFingerprint
from app.repositories.counterparty_fingerprint_repository import (
    CounterpartyFingerprintRepository,
)

logger = logging.getLogger(__name__)


class CounterpartyFingerprintService:
    """Phase 3 — counterparty-centric import.

    Services and UI resolve fingerprints to a counterparty first and only
    fall back to brand/fingerprint grouping when no binding exists. Bindings
    are created implicitly during bulk-apply when the user picks a
    counterparty for a cluster.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = CounterpartyFingerprintRepository(db)
        self._cache: dict[tuple[int, str], int] = {}

    def resolve(self, *, user_id: int, fingerprint: str) -> int | None:
        """Return counterparty_id if this fingerprint is bound, else None."""
        if not fingerprint:
            return None
        key = (user_id, fingerprint)
        if key in self._cache:
            return self._cache[key]
        binding = self.repo.get_by_fingerprint(user_id=user_id, fingerprint=fingerprint)
        cp_id = binding.counterparty_id if binding is not None else None
        if cp_id is not None:
            self._cache[key] = cp_id
        return cp_id

    def resolve_many(
        self, *, user_id: int, fingerprints: Iterable[str]
    ) -> dict[str, int]:
        """Batch-resolve: {fingerprint: counterparty_id} (only mapped ones)."""
        unique_fps = [fp for fp in set(fingerprints) if fp]
        if not unique_fps:
            return {}
        bindings = self.repo.list_by_fingerprints(
            user_id=user_id, fingerprints=unique_fps,
        )
        out: dict[str, int] = {}
        for b in bindings:
            out[b.fingerprint] = b.counterparty_id
            self._cache[(user_id, b.fingerprint)] = b.counterparty_id
        return out

    def bind(
        self,
        *,
        user_id: int,
        fingerprint: str,
        counterparty_id: int,
    ) -> CounterpartyFingerprint:
        """Create or strengthen a fingerprint→counterparty binding."""
        if not fingerprint:
            raise ValueError("fingerprint must be non-empty")
        binding, _is_new = self.repo.upsert(
            user_id=user_id,
            fingerprint=fingerprint,
            counterparty_id=counterparty_id,
        )
        self._cache[(user_id, fingerprint)] = counterparty_id
        return binding

    def bind_many(
        self,
        *,
        user_id: int,
        fingerprints: Iterable[str],
        counterparty_id: int,
    ) -> int:
        """Bind every unique fingerprint to the same counterparty.

        Called from bulk_apply_cluster — a cluster can span many fingerprints
        (brand cluster), and the user's single counterparty choice binds all
        of them at once. Returns the number of bindings created/updated.
        """
        seen: set[str] = set()
        count = 0
        for fp in fingerprints:
            if not fp or fp in seen:
                continue
            seen.add(fp)
            try:
                self.bind(
                    user_id=user_id,
                    fingerprint=fp,
                    counterparty_id=counterparty_id,
                )
                count += 1
            except Exception as exc:  # noqa: BLE001 — never block bulk-apply on binding errors
                logger.warning(
                    "counterparty binding failed user=%s fp=%s cp=%s: %s",
                    user_id, fp, counterparty_id, exc,
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
