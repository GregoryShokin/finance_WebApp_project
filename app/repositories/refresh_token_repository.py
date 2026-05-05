from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: int,
        token_hash: str,
        jti: str,
        expires_at: datetime,
        device_label: str | None = None,
    ) -> RefreshToken:
        record = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            jti=jti,
            expires_at=expires_at,
            device_label=device_label,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def get_by_hash(self, token_hash: str, *, for_update: bool = False) -> RefreshToken | None:
        query = self.db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash)
        if for_update:
            # Lock the row so two concurrent /auth/refresh calls with the same
            # token can't each pass the `revoked_at IS NULL` check before the
            # other one writes — without this, both would issue a fresh pair
            # off the same parent token.
            query = query.with_for_update()
        return query.first()

    def revoke(self, record: RefreshToken, *, now: datetime) -> None:
        if record.revoked_at is None:
            record.revoked_at = now
            self.db.add(record)
            self.db.flush()

    def revoke_all_for_user(self, *, user_id: int, now: datetime) -> int:
        """Mark every still-active refresh token for the user as revoked.

        Used as the response to a reuse-attack: the moment a previously revoked
        token comes back, every other token in the family is suspect.
        """
        updated = (
            self.db.query(RefreshToken)
            .filter(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .update({RefreshToken.revoked_at: now}, synchronize_session=False)
        )
        self.db.flush()
        return updated

    def prune_expired(self, *, now: datetime) -> int:
        """Delete tokens whose `expires_at` has passed. Returns count deleted."""
        deleted = (
            self.db.query(RefreshToken)
            .filter(RefreshToken.expires_at < now)
            .delete(synchronize_session=False)
        )
        self.db.flush()
        return deleted
