"""E2E test endpoints (`/api/v1/_test/*`).

These endpoints exist solely to support the Playwright suite under `e2e/`.
They MUST be disabled in production. Three layers of defence:

1. ``app/main.py`` registers this router only when
   ``settings.ENABLE_TEST_ENDPOINTS`` is True.
2. Every route here depends on :func:`require_test_endpoints_enabled`, so even
   if a future refactor wires the router unconditionally, requests still 404.
3. ``app/main.py`` aborts startup if ``APP_ENV`` is production AND the flag is
   True — a misconfigured deploy never even boots.

See E2E_SMOKE_TZ.md §5 for the full rationale.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)
from app.models.bank import Bank
from app.models.import_session import ImportSession
from app.models.user import User
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService, UserAlreadyExistsError


def require_test_endpoints_enabled() -> None:
    """Refuses the request when the flag is off — defence-in-depth.

    Returns 404 (not 403) so the endpoint is invisible to probing.
    """
    if not settings.ENABLE_TEST_ENDPOINTS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


router = APIRouter(
    prefix="/_test",
    tags=["_test (e2e suite only)"],
    dependencies=[Depends(require_test_endpoints_enabled)],
)


# ----- /seed/user -----------------------------------------------------------


class SeedUserRequest(BaseModel):
    # NOTE: plain str, not EmailStr. Pydantic's EmailStr rejects reserved TLDs
    # like ``.test``/``.example``, but the e2e suite generates emails such as
    # ``test-1714831234567@local.test`` for guaranteed uniqueness. The realistic
    # validation in production goes through register's normal flow; here we
    # just need a syntactic sanity check.
    email: str = Field(min_length=3, max_length=255, pattern=r".+@.+\..+")
    password: str = Field(min_length=1, max_length=200)
    full_name: str | None = None


class SeedUserResponse(BaseModel):
    user_id: int
    email: str
    access_token: str
    refresh_token: str
    created: bool


@router.post("/seed/user", response_model=SeedUserResponse)
def seed_user(payload: SeedUserRequest, db: Session = Depends(get_db)) -> SeedUserResponse:
    """Create or fetch a test user and issue a fresh token pair.

    Idempotent on email: if the user already exists, returns the existing
    record with new tokens so each test starts from a clean session.
    """
    auth = AuthService(db)
    repo = UserRepository(db)
    existing = repo.get_by_email(payload.email)
    created = False
    if existing is None:
        try:
            user = auth.register(
                email=payload.email,
                password=payload.password,
                full_name=payload.full_name,
            )
        except UserAlreadyExistsError as exc:  # pragma: no cover — race only
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        db.commit()
        created = True
    else:
        user = existing

    access = create_access_token(subject=user.id)
    refresh, jti, expires_at = create_refresh_token(subject=user.id)
    RefreshTokenRepository(db).create(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh),
        jti=jti,
        expires_at=expires_at,
        device_label="e2e-test",
    )
    db.commit()
    return SeedUserResponse(
        user_id=user.id,
        email=user.email,
        access_token=access,
        refresh_token=refresh,
        created=created,
    )


# ----- /seed/bank -----------------------------------------------------------


ExtractorStatus = Literal["supported", "in_review", "pending", "broken"]


class SeedBankRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    extractor_status: ExtractorStatus = "supported"
    code: str | None = None  # auto-derived from name if omitted


class SeedBankResponse(BaseModel):
    bank_id: int
    name: str
    extractor_status: ExtractorStatus
    created: bool
    previous_extractor_status: ExtractorStatus | None


@router.post("/seed/bank", response_model=SeedBankResponse)
def seed_bank(payload: SeedBankRequest, db: Session = Depends(get_db)) -> SeedBankResponse:
    """UPSERT bank by name. Phase 6 (bank guard) flips Сбер to ``pending`` and
    relies on this returning the previous status so teardown can restore it.
    """
    bank = db.query(Bank).filter(Bank.name == payload.name).one_or_none()
    if bank is None:
        bank = Bank(
            name=payload.name,
            code=payload.code or _derive_bank_code(payload.name),
            extractor_status=payload.extractor_status,
        )
        db.add(bank)
        db.commit()
        db.refresh(bank)
        return SeedBankResponse(
            bank_id=bank.id,
            name=bank.name,
            extractor_status=bank.extractor_status,  # type: ignore[arg-type]
            created=True,
            previous_extractor_status=None,
        )

    previous = bank.extractor_status
    bank.extractor_status = payload.extractor_status
    db.commit()
    db.refresh(bank)
    return SeedBankResponse(
        bank_id=bank.id,
        name=bank.name,
        extractor_status=bank.extractor_status,  # type: ignore[arg-type]
        created=False,
        previous_extractor_status=previous,  # type: ignore[arg-type]
    )


def _derive_bank_code(name: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    return f"test_{base}"[:64]


# ----- /seed/account --------------------------------------------------------


class SeedAccountRequest(BaseModel):
    user_id: int
    bank_id: int
    name: str = Field(min_length=1, max_length=255)
    currency: str = "RUB"
    account_type: str = "main"
    contract_number: str | None = None


class SeedAccountResponse(BaseModel):
    account_id: int


@router.post("/seed/account", response_model=SeedAccountResponse)
def seed_account(payload: SeedAccountRequest, db: Session = Depends(get_db)) -> SeedAccountResponse:
    from app.models.account import Account

    user = db.query(User).filter(User.id == payload.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    bank = db.query(Bank).filter(Bank.id == payload.bank_id).one_or_none()
    if bank is None:
        raise HTTPException(status_code=404, detail="bank not found")

    account = Account(
        user_id=payload.user_id,
        bank_id=payload.bank_id,
        name=payload.name,
        currency=payload.currency,
        account_type=payload.account_type,
        contract_number=payload.contract_number,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return SeedAccountResponse(account_id=account.id)


# ----- /cleanup/user --------------------------------------------------------


class CleanupUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, pattern=r".+@.+\..+")


class CleanupUserResponse(BaseModel):
    deleted: bool


@router.post("/cleanup/user", response_model=CleanupUserResponse)
def cleanup_user(payload: CleanupUserRequest, db: Session = Depends(get_db)) -> CleanupUserResponse:
    """Cascade-delete a test user. Returns ``deleted=False`` if no such user.

    Uses a RAW SQL DELETE rather than ``db.delete(user)`` to bypass an
    SQLAlchemy ORM ordering bug: when a user has both Categories and
    Budgets, the User-level cascade for Categories tries to nullify
    Budget.category_id BEFORE the User-level cascade for Budgets deletes
    them, hitting `NotNullViolation` on `budgets.category_id`. All
    `user_id` FKs in the schema have `ondelete=CASCADE` at the Postgres
    level, so a raw `DELETE FROM users` cascades cleanly without ORM
    inter-relationship ordering.
    """
    from sqlalchemy import text

    user = UserRepository(db).get_by_email(payload.email)
    if user is None:
        return CleanupUserResponse(deleted=False)
    user_id = user.id
    db.expunge(user)  # detach so subsequent flush doesn't try to manipulate it
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    db.commit()
    return CleanupUserResponse(deleted=True)


# ----- /reset/rate-limit ----------------------------------------------------


RateLimitScope = Literal["login", "register", "refresh", "upload", "bot_upload"]


class ResetRateLimitRequest(BaseModel):
    scope: RateLimitScope
    identifier: str | None = None  # IP for login/register/refresh/upload; user_id for upload too


class ResetRateLimitResponse(BaseModel):
    scope: RateLimitScope
    keys_deleted: int


_SCOPE_TO_ROUTE_FRAGMENT = {
    "login": "auth/login",
    "register": "auth/register",
    "refresh": "auth/refresh",
    "upload": "imports/upload",
    "bot_upload": "telegram/bot/upload",
}


@router.post("/reset/rate-limit", response_model=ResetRateLimitResponse)
def reset_rate_limit(payload: ResetRateLimitRequest) -> ResetRateLimitResponse:
    """Delete slowapi keys in Redis for the given scope.

    The `limits` library (used by slowapi) stores keys as
    ``LIMITS:LIMITER/<key_func_value>/<route>/<rate>/<window>/<unit>``. Because
    the route is part of the key, we match on a route fragment per scope (see
    `_SCOPE_TO_ROUTE_FRAGMENT`) — this is more reliable than matching on the
    scope name alone, which doesn't appear verbatim in the key.

    Safe to run in tests because Redis is shared only with Celery, and Celery
    keys (`celery-*`, `_kombu.*`) don't share the LIMITER prefix.
    """
    import redis

    fragment = _SCOPE_TO_ROUTE_FRAGMENT[payload.scope]
    client = redis.Redis.from_url(settings.REDIS_URL)

    # Pattern: LIMITS:LIMITER/<anything>/<fragment>/<rate-window-unit>
    if payload.identifier:
        pattern = f"LIMITS:LIMITER/*{payload.identifier}*{fragment}*"
    else:
        pattern = f"LIMITS:LIMITER/*{fragment}*"

    deleted = 0
    for key in client.scan_iter(match=pattern, count=100):
        deleted += int(client.delete(key))
    return ResetRateLimitResponse(scope=payload.scope, keys_deleted=deleted)


# ----- /auth/issue-tokens ---------------------------------------------------


class IssueTokensRequest(BaseModel):
    user_id: int
    access_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    refresh_ttl_seconds: int = Field(default=2592000, ge=1, le=2592000)


class IssueTokensResponse(BaseModel):
    access_token: str
    refresh_token: str
    access_ttl_seconds: int
    refresh_ttl_seconds: int


@router.post("/auth/issue-tokens", response_model=IssueTokensResponse)
def issue_tokens(payload: IssueTokensRequest, db: Session = Depends(get_db)) -> IssueTokensResponse:
    """Issue an access/refresh pair with custom TTLs. Used by scenario 0.1.7
    (silent-refresh test) so we don't have to wait the real 15 minutes.
    """
    user = db.query(User).filter(User.id == payload.user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    access = create_access_token(
        subject=user.id,
        expires_delta=timedelta(seconds=payload.access_ttl_seconds),
    )
    refresh, jti, expires_at = create_refresh_token(
        subject=user.id,
        expires_delta=timedelta(seconds=payload.refresh_ttl_seconds),
    )
    RefreshTokenRepository(db).create(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh),
        jti=jti,
        expires_at=expires_at,
        device_label="e2e-issue-tokens",
    )
    db.commit()
    return IssueTokensResponse(
        access_token=access,
        refresh_token=refresh,
        access_ttl_seconds=payload.access_ttl_seconds,
        refresh_ttl_seconds=payload.refresh_ttl_seconds,
    )


# ----- /import-session/{id} -------------------------------------------------


class ImportSessionStateResponse(BaseModel):
    id: int
    user_id: int
    status: str
    file_hash: str | None


@router.get("/import-session/{session_id}", response_model=ImportSessionStateResponse)
def get_import_session_state(
    session_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
) -> ImportSessionStateResponse:
    """Read-only peek into ImportSession state for dedup spec assertions."""
    session = (
        db.query(ImportSession).filter(ImportSession.id == session_id).one_or_none()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="import session not found")
    return ImportSessionStateResponse(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        file_hash=session.file_hash,
    )


@router.post("/import-session/{session_id}/mark-committed", response_model=ImportSessionStateResponse)
def mark_import_session_committed(
    session_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
) -> ImportSessionStateResponse:
    """Force-set ImportSession.status='committed' for dedup test 0.5.5.

    Driving the full upload→preview→mapping→commit flow through the UI just to
    arrive at "committed" state is ~10 brittle steps. This endpoint short-
    circuits to the only state the test cares about. Idempotent: hitting an
    already-committed session is a no-op.
    """
    session = (
        db.query(ImportSession).filter(ImportSession.id == session_id).one_or_none()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="import session not found")
    if session.status != "committed":
        session.status = "committed"
        db.commit()
        db.refresh(session)
    return ImportSessionStateResponse(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        file_hash=session.file_hash,
    )
