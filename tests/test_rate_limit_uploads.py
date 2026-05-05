"""Rate-limit tests for /imports/upload (per-user) and /telegram/bot/upload (per-IP).

Companion to test_rate_limit_auth.py — same MemoryStorage swap, same teardown
discipline. Validates two distinct key strategies introduced in commit 4:

  - **per-user via JWT decode** — `/imports/upload` uses `user_or_ip_key`,
    so two different access tokens get independent buckets even when the
    request reaches the server from the same TestClient peer.
  - **per-IP** — `/telegram/bot/upload` uses `ip_key`. Per-telegram_id was
    deliberately rejected because it would require parsing the multipart
    body twice (see backlog "Bot rate-limit per-telegram_id").

The "401 wins over 429" invariant is pinned by `test_invalid_token_returns_401_not_429`:
when `Depends(get_current_user)` rejects an unauth caller, the rate-limit
counter never increments. Documented in `architecture_decisions.md`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from starlette.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.imports import router as imports_router
from app.api.v1.telegram import require_bot_token, router as telegram_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token


# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def fresh_limiter_storage(monkeypatch):
    """Same pattern as test_rate_limit_auth: in-memory bucket store + reset.
    monkeypatch reverts `limiter._storage` and `limiter.enabled` after the
    test, so subsequent test files keep production behavior."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    new_storage = MemoryStorage()
    monkeypatch.setattr(limiter, "_storage", new_storage)
    # Strategy captures storage at __init__ — must rebuild it, otherwise
    # enforcement still hits the production (Redis) backend.
    monkeypatch.setattr(limiter, "_limiter", FixedWindowRateLimiter(new_storage))
    monkeypatch.setattr(limiter, "enabled", True)
    yield
    limiter.reset()


class _FakeService:
    """Stub ImportService — succeeds without touching extractors or DB."""

    def __init__(self, db):
        self.db = db

    def upload_source(self, *, user_id, filename, raw_bytes, delimiter, force_new=False):
        # `force_new` kwarg added in Этап 0.5 (duplicate-statement UX) — stub
        # silently accepts it; rate-limit tests don't exercise dedup logic.
        return {
            "session_id": 1,
            "filename": filename,
            "source_type": "csv",
            "status": "analyzed",
            "detected_columns": [],
            "sample_rows": [],
            "total_rows": 0,
        }


class _FakeUser:
    def __init__(self, user_id: int):
        self.id = user_id
        self.is_active = True
        self.email = f"u{user_id}@example.com"
        self.telegram_id = 1000 + user_id
        self.full_name = None


@pytest.fixture
def app(monkeypatch):
    import app.api.v1.imports as imports_module
    import app.api.v1.telegram as telegram_module

    monkeypatch.setattr(imports_module, "ImportService", _FakeService)
    monkeypatch.setattr(telegram_module, "ImportService", _FakeService)

    test_app = FastAPI()
    test_app.state.limiter = limiter
    from slowapi.errors import RateLimitExceeded
    from app.core.rate_limit import rate_limit_exceeded_handler
    test_app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    test_app.include_router(imports_router)
    test_app.include_router(telegram_router)

    # Holder mutated by tests to swap the "logged-in" user between requests.
    current = {"user": _FakeUser(1)}
    test_app.state._current_user_holder = current  # noqa: SLF001 — test helper

    class _DummySession:
        def query(self, _model):
            class _Q:
                def filter(self, *_a, **_kw): return self
                def first(self_inner): return current["user"]
            return _Q()
        def rollback(self): pass

    def _fake_db():
        yield _DummySession()

    def _fake_current_user():
        return current["user"]

    test_app.dependency_overrides[get_db] = _fake_db
    test_app.dependency_overrides[get_current_user] = _fake_current_user
    test_app.dependency_overrides[require_bot_token] = lambda: None
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


def _csv_body() -> bytes:
    # Tiny CSV — passes upload_validator (cp1251-tolerant negative check),
    # not testing extractors here.
    return b"date,amount\n2026-01-01,100\n"


def _bearer(user_id: int) -> dict[str, str]:
    """Real signed JWT — slowapi key_func runs `extract_subject_from_token`,
    so a hand-crafted dict body wouldn't be enough; we need the actual
    cryptographic shape."""
    return {"Authorization": f"Bearer {create_access_token(subject=user_id)}"}


# ─── /imports/upload — per-user via user_or_ip_key ───────────────────────────


def test_upload_per_user_isolation(client, app):
    """Same TestClient peer (one IP), two different access tokens → two
    independent buckets. Without per-user keying, user B's first upload
    would share the same counter as user A's saturated bucket."""
    user_a = _FakeUser(101)
    user_b = _FakeUser(202)
    holder = app.state._current_user_holder

    # User A: spend the entire 30/hour bucket.
    holder["user"] = user_a
    cap = int(settings.RATE_LIMIT_UPLOAD.split("/")[0])
    for _ in range(cap):
        r = client.post(
            "/imports/upload",
            files={"file": ("s.csv", _csv_body(), "text/csv")},
            headers=_bearer(user_a.id),
        )
        assert r.status_code == 201, r.text

    # User A: 31st → 429 (bucket saturated).
    r = client.post(
        "/imports/upload",
        files={"file": ("s.csv", _csv_body(), "text/csv")},
        headers=_bearer(user_a.id),
    )
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limit_exceeded"

    # User B: independent bucket — first upload still succeeds.
    holder["user"] = user_b
    r = client.post(
        "/imports/upload",
        files={"file": ("s.csv", _csv_body(), "text/csv")},
        headers=_bearer(user_b.id),
    )
    assert r.status_code == 201, r.text


def test_invalid_token_returns_401_not_429(client, app):
    """The "401 wins over 429" invariant. With a garbage Authorization
    header, `Depends(get_current_user)` rejects FIRST — the rate-limit
    decorator never increments. We send 35 requests (above the 30/hour cap):
    if the decorator counted them, the 31st would 429. Instead, all 35
    return 401 because auth fails before the limiter has anything to count.

    This pins the documented limitation in architecture_decisions.md:
    pre-auth IP rate-limiting on /imports/upload is NOT implemented;
    abuse of the route with garbage tokens is bounded only by the auth
    cost (JWT decode microseconds + DB lookup ~0.5ms via get_by_id).
    """
    # Override get_current_user to mimic the real "raise 401" behavior
    # instead of the fixture's tolerant fake.
    from fastapi import HTTPException

    def _strict_current_user():
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    app.dependency_overrides[get_current_user] = _strict_current_user

    cap = int(settings.RATE_LIMIT_UPLOAD.split("/")[0])
    for _ in range(cap + 5):
        r = client.post(
            "/imports/upload",
            files={"file": ("s.csv", _csv_body(), "text/csv")},
            headers={"Authorization": "Bearer garbage-not-a-jwt"},
        )
        assert r.status_code == 401, r.text


# ─── /telegram/bot/upload — per-IP via ip_key ────────────────────────────────


def test_bot_upload_per_ip_isolation(client, monkeypatch):
    """Two different "client IPs" get independent buckets. TestClient peer
    is fixed, so we monkey-patch the IP resolver — same trick as in
    test_rate_limit_auth.test_xff_used_when_proxy_trusted."""
    from app.core import client_ip as client_ip_module
    from app.core import keys as keys_module

    current_ip = {"value": "1.1.1.1"}
    monkeypatch.setattr(client_ip_module, "get_client_ip", lambda _r: current_ip["value"])
    monkeypatch.setattr(keys_module, "get_client_ip", lambda _r: current_ip["value"])

    cap = int(settings.RATE_LIMIT_BOT_UPLOAD.split("/")[0])

    # IP A: saturate bucket.
    current_ip["value"] = "1.1.1.1"
    for _ in range(cap):
        r = client.post(
            "/telegram/bot/upload",
            data={"telegram_id": "555", "delimiter": ","},
            files={"file": ("s.csv", _csv_body(), "text/csv")},
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/telegram/bot/upload",
        data={"telegram_id": "555", "delimiter": ","},
        files={"file": ("s.csv", _csv_body(), "text/csv")},
    )
    assert r.status_code == 429

    # IP B: untouched bucket.
    current_ip["value"] = "2.2.2.2"
    r = client.post(
        "/telegram/bot/upload",
        data={"telegram_id": "555", "delimiter": ","},
        files={"file": ("s.csv", _csv_body(), "text/csv")},
    )
    assert r.status_code == 201, r.text


def test_bot_upload_does_not_share_bucket_with_imports_upload(client, app, monkeypatch):
    """Sanity check on bucket key naming: even with the SAME apparent IP,
    `/imports/upload` (key_func=user_or_ip_key) and `/telegram/bot/upload`
    (key_func=ip_key) use different bucket prefixes via the slowapi
    per-decorator namespace, so saturating the bot route doesn't lock
    out the user route.

    If slowapi ever started collapsing buckets across decorators with
    different key_funcs but the same string output, this test catches it.
    """
    from app.core import client_ip as client_ip_module
    from app.core import keys as keys_module

    monkeypatch.setattr(client_ip_module, "get_client_ip", lambda _r: "9.9.9.9")
    monkeypatch.setattr(keys_module, "get_client_ip", lambda _r: "9.9.9.9")

    cap = int(settings.RATE_LIMIT_BOT_UPLOAD.split("/")[0])
    for _ in range(cap):
        client.post(
            "/telegram/bot/upload",
            data={"telegram_id": "555", "delimiter": ","},
            files={"file": ("s.csv", _csv_body(), "text/csv")},
        )
    # Bot bucket is saturated; user upload should still pass — different
    # decorator, different bucket.
    r = client.post(
        "/imports/upload",
        files={"file": ("s.csv", _csv_body(), "text/csv")},
        headers=_bearer(101),
    )
    assert r.status_code == 201, r.text
