from __future__ import annotations

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
