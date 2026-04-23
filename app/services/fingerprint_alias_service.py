from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.fingerprint_alias import FingerprintAlias
from app.repositories.fingerprint_alias_repository import FingerprintAliasRepository

logger = logging.getLogger(__name__)

# Defensive cap — alias chains should already be flattened at creation, but
# resolve() still walks the chain in case flattening missed something (e.g.
# concurrent writes from a parallel session).
_MAX_RESOLVE_DEPTH = 5


class FingerprintAliasService:
    """User-scoped fingerprint redirects (Level 3 cluster merging).

    When a user attaches an «Требуют внимания» row to an existing cluster, the
    source fingerprint gets an alias → target. Subsequent imports with the
    same source fingerprint are routed to the target cluster at normalization
    time, so the user doesn't have to re-attach on every statement.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = FingerprintAliasRepository(db)
        # Per-request cache — resolve() can be called many times during a
        # single normalization pass. One DB hit per unique fingerprint is
        # enough; the cache is reset when the service is recreated.
        self._cache: dict[tuple[int, str], str] = {}

    # ───────────────────────────────────────────────────────────────────
    # Read path — called from the normalizer for every row
    # ───────────────────────────────────────────────────────────────────

    def resolve(self, *, user_id: int, fingerprint: str) -> str:
        """Walk the alias chain, returning the final target fingerprint.

        If no alias exists for `fingerprint`, returns it unchanged. Cycles
        (shouldn't happen — we flatten on write — but just in case) are
        broken by the depth cap and a visited-set.
        """
        if not fingerprint:
            return fingerprint
        key = (user_id, fingerprint)
        if key in self._cache:
            return self._cache[key]

        visited: set[str] = set()
        current = fingerprint
        for _ in range(_MAX_RESOLVE_DEPTH):
            if current in visited:
                logger.warning(
                    "fingerprint_alias cycle detected user=%s start=%s current=%s",
                    user_id, fingerprint, current,
                )
                break
            visited.add(current)
            alias = self.repo.get_by_source(user_id=user_id, source_fingerprint=current)
            if alias is None:
                break
            if alias.target_fingerprint == current:
                break  # self-loop — shouldn't exist, but break defensively
            current = alias.target_fingerprint

        self._cache[key] = current
        return current

    def resolve_many(self, *, user_id: int, fingerprints: Iterable[str]) -> dict[str, str]:
        """Batch helper — returns {source_fp: resolved_fp}. Unknown sources
        map to themselves."""
        return {fp: self.resolve(user_id=user_id, fingerprint=fp) for fp in fingerprints}

    # ───────────────────────────────────────────────────────────────────
    # Write path — called when user attaches a row to a cluster
    # ───────────────────────────────────────────────────────────────────

    def create_alias(
        self,
        *,
        user_id: int,
        source_fingerprint: str,
        target_fingerprint: str,
    ) -> FingerprintAlias:
        """Redirect `source_fingerprint` → `target_fingerprint` for this user.

        Guarantees:
          - source ≠ target (no-op check — raises ValueError)
          - If target itself has an alias (target → X), we transparently
            redirect to X instead, so we never create a chain link.
          - Any existing aliases `? → source` are rewritten to point at the
            new target directly (chain flattening).
        """
        if not source_fingerprint or not target_fingerprint:
            raise ValueError("fingerprints must be non-empty")
        if source_fingerprint == target_fingerprint:
            raise ValueError("source and target fingerprints cannot be equal")

        # Flatten target if it's already aliased elsewhere. This also prevents
        # A → B when B → C already exists (stores A → C instead).
        final_target = self.resolve(
            user_id=user_id, fingerprint=target_fingerprint
        )
        if final_target == source_fingerprint:
            # Creating source → target would form a cycle (target eventually
            # resolves back to source). Reject.
            raise ValueError(
                "creating this alias would form a cycle "
                f"(resolving {target_fingerprint} lands at {source_fingerprint})"
            )

        alias, _is_new = self.repo.upsert(
            user_id=user_id,
            source_fingerprint=source_fingerprint,
            target_fingerprint=final_target,
        )

        # Flatten upstream — anyone who was pointing at our `source_fingerprint`
        # should now skip through to `final_target`.
        upstream = self.repo.list_pointing_to(
            user_id=user_id, target_fingerprint=source_fingerprint
        )
        for upstream_alias in upstream:
            if upstream_alias.id == alias.id:
                continue
            upstream_alias.target_fingerprint = final_target
        if upstream:
            self.db.flush()

        # Invalidate cache — aliases changed.
        self._cache.clear()
        return alias

    def delete_alias(self, *, user_id: int, source_fingerprint: str) -> bool:
        alias = self.repo.get_by_source(
            user_id=user_id, source_fingerprint=source_fingerprint
        )
        if alias is None:
            return False
        self.repo.delete(alias=alias)
        self._cache.clear()
        return True
