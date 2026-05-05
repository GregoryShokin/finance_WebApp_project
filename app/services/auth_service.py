from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import (
    InvalidTokenError,
    PasswordTooLongError,
    create_access_token,
    create_refresh_token,
    extract_refresh_payload,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.category_service import CategoryService
from app.services.goal_service import GoalService


class UserAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InactiveUserError(Exception):
    pass


class InvalidPasswordError(Exception):
    pass


class RefreshTokenInvalidError(Exception):
    """Refresh token is malformed, expired, missing, or has wrong type."""


class RefreshTokenReusedError(Exception):
    """A previously-revoked refresh token was presented again — reuse attack.

    The service has already revoked every other active token for the user
    by the time this is raised; the API just maps it to 401.
    """


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

    def register(self, *, email: str, password: str, full_name: str | None = None) -> User:
        if self.user_repo.get_by_email(email):
            raise UserAlreadyExistsError("User with this email already exists")
        try:
            password_hash = hash_password(password)
        except PasswordTooLongError as exc:
            raise InvalidPasswordError('Password is too long. Maximum allowed length is 72 bytes in UTF-8.') from exc
        user = self.user_repo.create(email=email, password_hash=password_hash, full_name=full_name)
        CategoryService(self.db).ensure_default_categories(user_id=user.id)
        GoalService(self.db).ensure_system_goals(user.id)
        return user

    def login(
        self,
        *,
        email: str,
        password: str,
        device_label: str | None = None,
    ) -> tuple[str, str]:
        """Authenticate and issue an (access, refresh) pair.

        Multi-device by design (Этап 0.1, 2026-05-03): existing refresh tokens
        for the user are NOT revoked — desktop + mobile + Telegram-linked sessions
        all coexist.
        """
        user = self.user_repo.get_by_email(email)
        if not user:
            raise InvalidCredentialsError("Invalid email or password")
        try:
            password_ok = verify_password(password, user.password_hash)
        except PasswordTooLongError:
            raise InvalidCredentialsError("Invalid email or password")
        if not password_ok:
            raise InvalidCredentialsError("Invalid email or password")
        if not user.is_active:
            raise InactiveUserError("User is inactive")

        access = create_access_token(subject=user.id)
        refresh = self._issue_refresh(user_id=user.id, device_label=device_label)
        self.db.commit()
        return access, refresh

    def refresh(
        self,
        *,
        refresh_token: str,
        device_label: str | None = None,
    ) -> tuple[str, str]:
        """Rotate the refresh token and return a fresh (access, refresh) pair.

        Failure modes:
        - Bad signature, expired exp, wrong type, missing claims → InvalidTokenError → InvalidError.
        - Token absent from DB (e.g. pruned after expiry) → InvalidError. NOT treated as reuse:
          a missing record can be a legitimate stale client, while a present-but-revoked
          record is the actual reuse signal.
        - Token present but already revoked → revoke_all_for_user, then ReusedError.
        - Token present, not revoked, expires_at < now → InvalidError (no revoke_all).
        - Owner user inactive/missing → InvalidError.
        """
        try:
            subject, _jti = extract_refresh_payload(refresh_token)
        except InvalidTokenError as exc:
            raise RefreshTokenInvalidError(str(exc)) from exc

        try:
            user_id = int(subject)
        except ValueError as exc:
            raise RefreshTokenInvalidError("Invalid subject") from exc

        record = self.refresh_repo.get_by_hash(hash_refresh_token(refresh_token), for_update=True)
        if record is None:
            raise RefreshTokenInvalidError("Refresh token not recognized")

        now = datetime.now(timezone.utc)

        if record.revoked_at is not None:
            self.refresh_repo.revoke_all_for_user(user_id=record.user_id, now=now)
            self.db.commit()
            raise RefreshTokenReusedError("Refresh token was already revoked")

        record_expires_at = self._as_utc(record.expires_at)
        if record_expires_at < now:
            raise RefreshTokenInvalidError("Refresh token expired")

        if record.user_id != user_id:
            raise RefreshTokenInvalidError("Refresh token user mismatch")

        user = self.user_repo.get_by_id(user_id)
        if user is None or not user.is_active:
            raise RefreshTokenInvalidError("User not available")

        self.refresh_repo.revoke(record, now=now)
        next_label = device_label if device_label is not None else record.device_label
        access = create_access_token(subject=user.id)
        new_refresh = self._issue_refresh(user_id=user.id, device_label=next_label)
        self.db.commit()
        return access, new_refresh

    def logout(self, *, refresh_token: str) -> None:
        """Revoke a refresh token. Idempotent — unknown/invalid tokens silently no-op."""
        try:
            extract_refresh_payload(refresh_token)
        except InvalidTokenError:
            return

        record = self.refresh_repo.get_by_hash(hash_refresh_token(refresh_token))
        if record is None:
            return

        self.refresh_repo.revoke(record, now=datetime.now(timezone.utc))
        self.db.commit()

    def _issue_refresh(self, *, user_id: int, device_label: str | None) -> str:
        token, jti, expires_at = create_refresh_token(subject=user_id)
        self.refresh_repo.create(
            user_id=user_id,
            token_hash=hash_refresh_token(token),
            jti=jti,
            expires_at=expires_at,
            device_label=self._truncate_label(device_label),
        )
        return token

    @staticmethod
    def _truncate_label(label: str | None) -> str | None:
        if label is None:
            return None
        clean = label.strip()
        if not clean:
            return None
        return clean[:255]

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Postgres returns timezone-aware datetimes; SQLite-in-tests may return naive ones."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
