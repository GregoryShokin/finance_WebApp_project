from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)

MAX_PASSWORD_BYTES = 1024


class PasswordTooLongError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


def _validate_password_bytes(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"Password is too long. Maximum allowed length is {MAX_PASSWORD_BYTES} bytes in UTF-8."
        )


def hash_password(password: str) -> str:
    _validate_password_bytes(password)
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    _validate_password_bytes(plain_password)
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def extract_subject_from_token(token: str) -> str:
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise InvalidTokenError("Invalid token type")
        subject = payload.get("sub")
        if not subject:
            raise InvalidTokenError("Token payload missing subject")
        return str(subject)
    except JWTError as exc:
        raise InvalidTokenError("Invalid token") from exc


def create_refresh_token(
    subject: str | Any,
    expires_delta: timedelta | None = None,
) -> tuple[str, str, datetime]:
    """Issue a refresh JWT.

    Returns (token, jti, expires_at). Caller stores `sha256(token)` and `jti`
    in the DB; the raw token is shown to the client exactly once.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": jti,
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti, expire


def extract_refresh_payload(token: str) -> tuple[str, str]:
    """Validate a refresh JWT and return (subject, jti).

    Raises `InvalidTokenError` on bad signature, expired exp, wrong type,
    or missing sub/jti claims. Never returns None.
    """
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise InvalidTokenError("Invalid token type")
        subject = payload.get("sub")
        jti = payload.get("jti")
        if not subject or not jti:
            raise InvalidTokenError("Token payload missing subject or jti")
        return str(subject), str(jti)
    except JWTError as exc:
        raise InvalidTokenError("Invalid token") from exc


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest of the raw token string. DB stores this, never the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
