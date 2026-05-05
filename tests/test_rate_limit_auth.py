"""Rate-limit tests for /auth/login, /auth/register, /auth/refresh.

The auth-service business logic is tested in test_auth_refresh.py — here we
care only about the rate-limit boundary and 429 contract.

Storage strategy: the production `limiter` instance points at Redis
(`storage_uri=settings.REDIS_URL`). In tests we don't want to require a live
Redis, so we swap the storage to in-memory via `MemoryStorage` per fixture
and reset between tests. This exercises the same decorators, the same
`Limiter` instance, the same `_check_request_limit` codepath — only the
counter store differs.

Why this isn't a global conftest fixture: other test modules
(test_auth_refresh.py, test_imports_upload_validation.py, …) call /auth/login
or rely on it being un-throttled. Forcing rate-limit-on globally would make
those suites flaky once they hit the 5-attempt cap. Limiter scope stays
local to this file.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from starlette.testclient import TestClient

from app.api.v1.auth import router as auth_router
from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import limiter


PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fresh_limiter_storage(monkeypatch):
    """Force in-memory storage and re-enable the limiter for THIS file only.

    `monkeypatch.setattr` reverts attributes back to their originals after the
    fixture finishes — without that, swapping `limiter._storage` here would
    leave the global limiter pointing at MemoryStorage for any later test
    file in the same pytest process. `limiter.reset()` after the test body
    additionally drains the swapped MemoryStorage so each test starts with
    empty buckets.
    """
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    new_storage = MemoryStorage()
    monkeypatch.setattr(limiter, "_storage", new_storage)
    # The strategy object captures the storage reference at __init__, so
    # swapping `_storage` alone leaves enforcement pointed at the old
    # (Redis) backend. Rebuild the strategy with the new in-memory store.
    monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(new_storage))
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


def _build_app(db_session):
    """Mount auth router with a stub get_db. We don't need a real session for
    rate-limit tests — the limiter rejects BEFORE the route runs body logic,
    and 401/200 paths just need a session object to satisfy Depends."""
    test_app = FastAPI()
    test_app.state.limiter = limiter
    from slowapi.errors import RateLimitExceeded
    from app.core.rate_limit import rate_limit_exceeded_handler
    test_app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    test_app.include_router(auth_router)

    def _override_db():
        yield db_session

    test_app.dependency_overrides[get_db] = _override_db
    return test_app


@pytest.fixture
def client(db):
    """`db` comes from conftest.py — sqlite in-memory session, fresh per test."""
    return TestClient(_build_app(db))


@pytest.fixture
def registered_user(db):
    """Real bcrypt user so /auth/login can succeed (needed to count 200s as
    rate-limit hits — slowapi increments on every reach, not just on errors)."""
    from app.models.user import User
    from app.core.security import hash_password

    u = User(email="ratelimit@example.com", password_hash=hash_password(PASSWORD), is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ─── /auth/login (5 / 15 minutes per IP) ─────────────────────────────────────


def test_login_under_limit_passes(client, registered_user):
    """Five attempts in the 15-minute window must all reach the route. Wrong
    password gives 401, the rate-limit decorator is silent."""
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"email": registered_user.email, "password": "wrong-password-here"},
        )
        assert response.status_code == 401, response.text


def test_login_over_limit_returns_429_with_payload(client, registered_user):
    """6th attempt → 429. Payload contract is fixed (frontend depends on it)."""
    for _ in range(5):
        client.post(
            "/auth/login",
            json={"email": registered_user.email, "password": "wrong-pw-here"},
        )
    response = client.post(
        "/auth/login",
        json={"email": registered_user.email, "password": "wrong-pw-here"},
    )
    assert response.status_code == 429, response.text
    payload = response.json()
    assert payload["code"] == "rate_limit_exceeded"
    assert payload["retry_after_seconds"] >= 1
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) >= 1
    # Sanity: this also confirms slowapi parsed `5/15 minutes` correctly.
    # If the format string were ignored, all 6 attempts would have returned 401.


def test_xff_used_when_proxy_trusted(client, registered_user, monkeypatch):
    """When TRUSTED_PROXIES contains the test peer, XFF picks the real IP.
    Two different X-Forwarded-For values get independent buckets."""
    # TestClient peer is 'testclient' but settings parsing accepts CIDR/IPs;
    # we trust everything by patching get_client_ip directly so the test
    # doesn't depend on TestClient transport internals.
    from app.core import client_ip as client_ip_module

    current_ip = {"value": "1.1.1.1"}

    def _fake_resolver(_request):
        return current_ip["value"]

    monkeypatch.setattr(client_ip_module, "get_client_ip", _fake_resolver)
    # The keys module imported `get_client_ip` at import time, so patch it there too.
    from app.core import keys as keys_module
    monkeypatch.setattr(keys_module, "get_client_ip", _fake_resolver)

    # IP A: 5 attempts succeed (401 wrong pw), 6th → 429.
    current_ip["value"] = "1.1.1.1"
    for _ in range(5):
        client.post("/auth/login", json={"email": registered_user.email, "password": "wrong-pw-here"})
    r = client.post("/auth/login", json={"email": registered_user.email, "password": "wrong-pw-here"})
    assert r.status_code == 429

    # IP B: completely independent bucket — first request still passes.
    current_ip["value"] = "2.2.2.2"
    r = client.post("/auth/login", json={"email": registered_user.email, "password": "wrong-pw-here"})
    assert r.status_code == 401, r.text


def test_xff_ignored_when_proxy_untrusted(client, registered_user, monkeypatch):
    """TRUSTED_PROXIES=[] (default) → XFF ignored, all requests share the
    underlying TestClient peer's bucket. Five spoofed XFFs all count toward
    the same limit."""
    # Don't monkey-patch resolver here — let the real one run with empty
    # TRUSTED_PROXIES. All requests resolve to TestClient's actual peer
    # ('testclient'), so they share one bucket regardless of XFF header.
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", [])
    from app.core.client_ip import _trusted_networks
    _trusted_networks.cache_clear()

    spoofed_ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4", "10.0.0.5"]
    for ip in spoofed_ips:
        client.post(
            "/auth/login",
            json={"email": registered_user.email, "password": "wrong-pw-here"},
            headers={"X-Forwarded-For": ip},
        )
    # 6th request from yet another spoofed IP → still hits the limit because
    # all five above counted to the SAME bucket (the real test peer).
    response = client.post(
        "/auth/login",
        json={"email": registered_user.email, "password": "wrong-pw-here"},
        headers={"X-Forwarded-For": "99.99.99.99"},
    )
    assert response.status_code == 429
    assert response.json()["code"] == "rate_limit_exceeded"


# ─── /auth/register (3 / hour per IP) ────────────────────────────────────────


def test_register_over_limit_returns_429(client):
    """Distinct emails so each registration would otherwise succeed; only
    rate-limit can stop the 4th."""
    for i in range(3):
        r = client.post(
            "/auth/register",
            json={"email": f"new{i}@example.com", "password": PASSWORD, "full_name": None},
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/auth/register",
        json={"email": "new3@example.com", "password": PASSWORD, "full_name": None},
    )
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limit_exceeded"


# ─── /auth/refresh (30 / 5 minutes per IP) ───────────────────────────────────


def test_refresh_over_limit_returns_429(client, registered_user):
    """Confirm the third auth endpoint also enforces its decorator. We send
    a garbage refresh-token: the route returns 401 each time, but slowapi
    counts every reach, not just successes — so the 31st call hits 429."""
    payload = {"refresh_token": "not-a-real-jwt"}
    for _ in range(30):
        r = client.post("/auth/refresh", json=payload)
        assert r.status_code == 401, r.text
    r = client.post("/auth/refresh", json=payload)
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limit_exceeded"
