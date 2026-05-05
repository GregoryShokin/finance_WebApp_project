"""Refresh-token tests for Этап 0.1.

NOTE: FOR UPDATE locks are silently parsed-but-ignored by SQLite. The race
condition in `AuthService.refresh()` is therefore validated by code shape
(the lock is requested via `with_for_update()`), not by behavior under
contention. Real lock validation requires Postgres + concurrent clients —
deferred to the future "integration tests on real Postgres" backlog item.



Covers the security invariants that are easy to silently break in a refactor:

- Rotation: every successful /auth/refresh revokes the parent token.
- Reuse-detection: presenting an already-revoked token revokes EVERY active
  token for the user. Required for compliance with OAuth 2.0 BCP §4.13.
- Reuse vs unknown: a token that is simply absent from the DB (e.g. pruned
  after expiry) MUST NOT trigger reuse-detection — it can be a stale client.
- Type confusion: an access token presented to /auth/refresh must 401, not 500.
- Multi-device: a second login does not invalidate the first session.
- Idempotent logout: revoking the same token twice (or revoking an unknown
  token) is a no-op.

Tests run against the SQLite in-memory fixture from conftest.py — no Docker
required. To exercise an expired refresh token without freezing time we mint
the JWT manually with `exp` in the past; this hits the same `InvalidTokenError`
path as a clock-driven expiry would.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
)
from app.models.refresh_token import RefreshToken
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    RefreshTokenInvalidError,
    RefreshTokenReusedError,
)


# ─── helpers ──────────────────────────────────────────────────────────────────


PASSWORD = "correct horse battery staple"


@pytest.fixture
def auth_user(db):
    """User row with a real bcrypt password hash so login() can be exercised end-to-end."""
    from app.models.user import User

    u = User(email="auth@example.com", password_hash=hash_password(PASSWORD), is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def service(db):
    return AuthService(db)


def _mint_expired_refresh(user_id: int) -> str:
    """Forge a syntactically valid refresh JWT with `exp` in the past.

    Avoids pulling in freezegun for one negative-path test. The signature is
    real — only `exp` differs from a freshly issued token.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int((now - timedelta(days=2)).timestamp()),
        "nbf": int((now - timedelta(days=2)).timestamp()),
        "exp": int((now - timedelta(days=1)).timestamp()),
        "jti": uuid.uuid4().hex,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _count_active(db, user_id: int) -> int:
    return (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .count()
    )


# ─── login ────────────────────────────────────────────────────────────────────


def test_login_returns_pair_and_persists_refresh_record(service, auth_user, db):
    access, refresh = service.login(email=auth_user.email, password=PASSWORD)

    assert isinstance(access, str) and access
    assert isinstance(refresh, str) and refresh
    assert access != refresh

    record = RefreshTokenRepository(db).get_by_hash(hash_refresh_token(refresh))
    assert record is not None
    assert record.user_id == auth_user.id
    assert record.revoked_at is None
    assert record.expires_at > datetime.now(timezone.utc)


def test_login_with_wrong_password_does_not_create_refresh(service, auth_user, db):
    with pytest.raises(InvalidCredentialsError):
        service.login(email=auth_user.email, password="wrong")
    assert db.query(RefreshToken).count() == 0


def test_login_records_device_label_truncated(service, auth_user, db):
    long_label = "Mozilla/5.0 " + "X" * 1000
    _, refresh = service.login(email=auth_user.email, password=PASSWORD, device_label=long_label)
    record = RefreshTokenRepository(db).get_by_hash(hash_refresh_token(refresh))
    assert record.device_label is not None
    assert len(record.device_label) <= 255


# ─── refresh: happy path & rotation ───────────────────────────────────────────


def test_refresh_rotates_and_revokes_parent(service, auth_user, db):
    _, refresh1 = service.login(email=auth_user.email, password=PASSWORD)
    access2, refresh2 = service.refresh(refresh_token=refresh1)

    assert refresh2 != refresh1
    repo = RefreshTokenRepository(db)
    parent = repo.get_by_hash(hash_refresh_token(refresh1))
    child = repo.get_by_hash(hash_refresh_token(refresh2))

    assert parent is not None and parent.revoked_at is not None
    assert child is not None and child.revoked_at is None
    assert isinstance(access2, str) and access2


def test_refresh_three_rotations_chain(service, auth_user):
    _, r1 = service.login(email=auth_user.email, password=PASSWORD)
    _, r2 = service.refresh(refresh_token=r1)
    _, r3 = service.refresh(refresh_token=r2)
    _, r4 = service.refresh(refresh_token=r3)
    assert len({r1, r2, r3, r4}) == 4


def test_refresh_propagates_device_label_when_caller_omits_it(service, auth_user, db):
    _, r1 = service.login(email=auth_user.email, password=PASSWORD, device_label="Firefox")
    _, r2 = service.refresh(refresh_token=r1, device_label=None)
    child = RefreshTokenRepository(db).get_by_hash(hash_refresh_token(r2))
    assert child.device_label == "Firefox"


# ─── refresh: reuse detection ─────────────────────────────────────────────────


def test_revoked_refresh_triggers_reuse_detection_revokes_all(service, auth_user, db):
    _, r1 = service.login(email=auth_user.email, password=PASSWORD)
    _, r2 = service.login(email=auth_user.email, password=PASSWORD)  # second device
    _, r3 = service.refresh(refresh_token=r1)
    # r1 is now revoked. Replaying it must revoke EVERY active token (r2, r3).

    assert _count_active(db, auth_user.id) == 2  # r2 + r3

    with pytest.raises(RefreshTokenReusedError):
        service.refresh(refresh_token=r1)

    assert _count_active(db, auth_user.id) == 0


def test_unknown_refresh_token_is_invalid_not_reuse(service, auth_user, db):
    """A token absent from the DB is rejected as invalid, NOT as reuse —
    otherwise pruned-but-still-valid clients would discover their natural
    expiry as a global logout."""
    _, r1 = service.login(email=auth_user.email, password=PASSWORD)
    # mint a brand-new refresh JWT for the same user that was never persisted
    orphan, _, _ = create_refresh_token(subject=auth_user.id)

    with pytest.raises(RefreshTokenInvalidError):
        service.refresh(refresh_token=orphan)

    # r1 must still be valid — invalid != reuse
    assert _count_active(db, auth_user.id) == 1


# ─── refresh: type confusion / expiry ─────────────────────────────────────────


def test_access_token_rejected_on_refresh(service, auth_user):
    access = create_access_token(subject=auth_user.id)
    with pytest.raises(RefreshTokenInvalidError):
        service.refresh(refresh_token=access)


def test_garbage_token_rejected_on_refresh(service):
    with pytest.raises(RefreshTokenInvalidError):
        service.refresh(refresh_token="not-a-jwt")


def test_expired_refresh_token_is_invalid_no_revoke_all(service, auth_user, db):
    _, r1 = service.login(email=auth_user.email, password=PASSWORD)
    expired = _mint_expired_refresh(auth_user.id)

    with pytest.raises(RefreshTokenInvalidError):
        service.refresh(refresh_token=expired)

    # r1 must still be active — expired-elsewhere must not cascade to revoke_all
    assert _count_active(db, auth_user.id) == 1


# ─── multi-device isolation ───────────────────────────────────────────────────


def test_login_does_not_revoke_existing_sessions(service, auth_user, db):
    _, r1 = service.login(email=auth_user.email, password=PASSWORD)
    _, r2 = service.login(email=auth_user.email, password=PASSWORD)
    assert r1 != r2
    assert _count_active(db, auth_user.id) == 2


def test_refresh_one_device_does_not_affect_another(service, auth_user, db):
    _, r_phone = service.login(email=auth_user.email, password=PASSWORD)
    _, r_desktop = service.login(email=auth_user.email, password=PASSWORD)

    _, r_desktop_2 = service.refresh(refresh_token=r_desktop)

    # phone token must still be usable
    _, r_phone_2 = service.refresh(refresh_token=r_phone)
    assert r_phone_2 != r_desktop_2


# ─── logout ───────────────────────────────────────────────────────────────────


def test_logout_revokes_token_and_subsequent_refresh_fails(service, auth_user):
    _, r = service.login(email=auth_user.email, password=PASSWORD)
    service.logout(refresh_token=r)
    # Reusing a logged-out token is the same as reusing any revoked token →
    # reuse-detection fires.
    with pytest.raises(RefreshTokenReusedError):
        service.refresh(refresh_token=r)


def test_logout_idempotent_on_repeat(service, auth_user):
    _, r = service.login(email=auth_user.email, password=PASSWORD)
    service.logout(refresh_token=r)
    # second call must not raise; record stays revoked
    service.logout(refresh_token=r)


def test_logout_with_garbage_token_is_no_op(service):
    service.logout(refresh_token="not-a-jwt")
    service.logout(refresh_token="")


def test_logout_with_unknown_valid_token_is_no_op(service, auth_user):
    orphan, _, _ = create_refresh_token(subject=auth_user.id)
    # never persisted → silently does nothing, no exception
    service.logout(refresh_token=orphan)


# ─── repository: prune & revoke_all ───────────────────────────────────────────


def test_prune_expired_removes_only_past_expiry(db, auth_user):
    repo = RefreshTokenRepository(db)
    now = datetime.now(timezone.utc)

    repo.create(
        user_id=auth_user.id,
        token_hash="alive",
        jti="j1",
        expires_at=now + timedelta(days=1),
    )
    repo.create(
        user_id=auth_user.id,
        token_hash="dead",
        jti="j2",
        expires_at=now - timedelta(seconds=1),
    )
    db.commit()

    deleted = repo.prune_expired(now=now)
    db.commit()

    assert deleted == 1
    remaining = db.query(RefreshToken).filter(RefreshToken.user_id == auth_user.id).all()
    assert len(remaining) == 1
    assert remaining[0].token_hash == "alive"


def test_revoke_all_for_user_only_marks_active_tokens(db, auth_user):
    repo = RefreshTokenRepository(db)
    now = datetime.now(timezone.utc)
    earlier = now - timedelta(hours=1)

    active1 = repo.create(
        user_id=auth_user.id,
        token_hash="a1",
        jti="ja1",
        expires_at=now + timedelta(days=1),
    )
    active2 = repo.create(
        user_id=auth_user.id,
        token_hash="a2",
        jti="ja2",
        expires_at=now + timedelta(days=1),
    )
    already_revoked = repo.create(
        user_id=auth_user.id,
        token_hash="r1",
        jti="jr1",
        expires_at=now + timedelta(days=1),
    )
    already_revoked.revoked_at = earlier
    db.add(already_revoked)
    db.commit()

    affected = repo.revoke_all_for_user(user_id=auth_user.id, now=now)
    db.commit()

    assert affected == 2
    db.refresh(active1)
    db.refresh(active2)
    db.refresh(already_revoked)
    assert active1.revoked_at == now
    assert active2.revoked_at == now
    # untouched — keeps its earlier timestamp
    assert already_revoked.revoked_at == earlier
