"""Slowapi limiter setup + structured 429 handler.

Architectural decisions (see `architecture_decisions.md` block "Rate limits"):

  - **Decorator-only enforcement.** Slowapi's middleware skips routes that
    carry a `@limiter.limit(...)` decorator (`_should_exempt` in the source);
    the decorator runs inside FastAPI's dependency cycle, after `Depends`.
    That means brute-force traffic acquires a DB connection from the pool
    before hitting 429 — a perf nuance, not a security hole. Pre-auth IP
    rate-limiting (e.g. nginx) is a deferred backlog item.
  - **`default_limits=[]` is mandatory.** Without an explicit empty list a
    future copy-paste of `Limiter(default_limits=["100/hour"])` would silently
    cap every undecorated route, including `/health` (kubelet probes).
  - **Redis storage shared with Celery.** Multi-worker setups need a shared
    counter; per-process counters let an attacker cycle through workers.
  - **`headers_enabled=False`.** Slowapi's wrapper for decorated routes calls
    `_inject_headers` on every successful response and requires either the
    handler to return a `Response` object or to declare `response: Response`
    in its signature. Neither is true for our routes (they return Pydantic
    models). With `headers_enabled=False` the wrapper short-circuits, leaving
    the 429 path (which carries its own `Retry-After`) untouched. The
    "N tries left" UX (`X-RateLimit-Remaining`) is a backlog item — when we
    add it, every rate-limited handler needs `response: Response` and we can
    flip this back on.
  - **`SlowAPIMiddleware` is registered for symmetry** — it does NOT enforce
    on decorated routes (`_should_exempt` skips them) and with
    `headers_enabled=False` it also does NOT inject headers for non-decorated
    routes. Kept in the stack so a future copy-paste of an undecorated route
    + global default still works without re-registration.
"""
from __future__ import annotations

import logging

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.keys import ip_key  # default key — most routes override per-decorator


logger = logging.getLogger(__name__)


# Centralized limiter instance. Routes import `limiter` and decorate via
# `@limiter.limit(settings.RATE_LIMIT_*)`. The `key_func` set here is the
# fallback for any decorator that omits `key_func=...`; per-route overrides
# are explicit (see `app/core/keys.py`).
limiter = Limiter(
    key_func=ip_key,
    storage_uri=settings.REDIS_URL,
    default_limits=[],  # NEVER add globals here — see module docstring
    enabled=settings.RATE_LIMIT_ENABLED,
    # See module docstring: slowapi's wrapper requires `response: Response` in
    # the handler signature for header injection on success. Our handlers
    # return Pydantic models, so we keep headers off until the "N tries left"
    # UX is wired up.
    headers_enabled=False,
)


def _endpoint_name(request: Request) -> str:
    """Best-effort route identifier for the 429 payload.

    `request.scope["route"]` is populated only after FastAPI has resolved the
    handler; on the slowapi enforcement path it usually IS populated (decorator
    runs after route resolution). Fall back to `url.path` so the user always
    sees something concrete instead of "unknown".
    """
    route = request.scope.get("route")
    name = getattr(route, "name", None)
    if name:
        return name
    return request.url.path


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Emit a structured 429 with `Retry-After` (RFC 7231 seconds form).

    `exc.retry_after` may be 0 in edge cases (the bucket already crossed the
    boundary); guard with `max(int(...), 1)` so the client always sees a
    plausible delay rather than "retry now" which would just bounce again.
    """
    retry_after = max(int(getattr(exc, "retry_after", 0) or 0), 1)
    payload = {
        "detail": f"Слишком много запросов. Повтори через {retry_after} сек.",
        "code": "rate_limit_exceeded",
        "endpoint": _endpoint_name(request),
        "retry_after_seconds": retry_after,
    }
    return JSONResponse(
        status_code=429,
        content=payload,
        headers={"Retry-After": str(retry_after)},
    )
