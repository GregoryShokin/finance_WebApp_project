from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.fingerprint_alias import FingerprintAlias


class FingerprintAliasRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_source(self, *, user_id: int, source_fingerprint: str) -> FingerprintAlias | None:
        return (
            self.db.query(FingerprintAlias)
            .filter(
                FingerprintAlias.user_id == user_id,
                FingerprintAlias.source_fingerprint == source_fingerprint,
            )
            .first()
        )

    def list_by_user(self, *, user_id: int) -> list[FingerprintAlias]:
        return (
            self.db.query(FingerprintAlias)
            .filter(FingerprintAlias.user_id == user_id)
            .all()
        )

    def list_pointing_to(self, *, user_id: int, target_fingerprint: str) -> list[FingerprintAlias]:
        """All aliases whose target == given fingerprint. Used for chain flattening."""
        return (
            self.db.query(FingerprintAlias)
            .filter(
                FingerprintAlias.user_id == user_id,
                FingerprintAlias.target_fingerprint == target_fingerprint,
            )
            .all()
        )

    def upsert(
        self,
        *,
        user_id: int,
        source_fingerprint: str,
        target_fingerprint: str,
    ) -> tuple[FingerprintAlias, bool]:
        """Create or update an alias. Returns (alias, is_new).

        If an alias already exists for (user, source), its target is
        overwritten and confirms incremented. Callers are responsible for
        chain flattening via FingerprintAliasService.
        """
        alias = self.get_by_source(user_id=user_id, source_fingerprint=source_fingerprint)
        is_new = alias is None
        if alias is None:
            alias = FingerprintAlias(
                user_id=user_id,
                source_fingerprint=source_fingerprint,
                target_fingerprint=target_fingerprint,
                confirms=1,
            )
            self.db.add(alias)
        else:
            alias.target_fingerprint = target_fingerprint
            alias.confirms = (alias.confirms or 0) + 1
        self.db.flush()
        return alias, is_new

    def delete(self, *, alias: FingerprintAlias) -> None:
        self.db.delete(alias)
        self.db.flush()
