"""Slowapi key functions — derive a stable per-request bucket id.

Each function MUST:
  - never raise (a key_func crash kills the route, not just the limit check),
  - return a string distinct between users / IPs / bots so counters don't merge.

Two strategies:
  - `ip_key` — pure client-IP. Used for unauthenticated endpoints
    (`/auth/login`, `/register`, `/refresh`) and for the bot upload route
    (per-IP since extracting `telegram_id` would require parsing a 25 MB
    multipart body twice — see Этап 0.3 dossier).
  - `user_or_ip_key` — JWT subject if a Bearer token is present and decodable,
    otherwise IP. Used for `/imports/upload`: same authenticated user from two
    devices shares one bucket, while CGNAT users on a shared IP don't.

Why JWT decode here, not `request.state.user`: `get_current_user` is a FastAPI
`Depends`, not a middleware, so it doesn't populate `request.state` on the
slowapi enforcement path. Decoding the token twice (here + inside Depends) is
microseconds. TODO: collapse to `request.state.user` if/when auth moves to
middleware.
"""
from __future__ import annotations

import logging

from starlette.requests import Request

from app.core.client_ip import get_client_ip
from app.core.security import extract_subject_from_token


logger = logging.getLogger(__name__)


def ip_key(request: Request) -> str:
    return f"ip:{get_client_ip(request)}"


def user_or_ip_key(request: Request) -> str:
    """JWT-subject when present, IP otherwise. Defensive: any failure path
    falls through to IP — a key_func that raises kills the request, not just
    the rate limit check."""
    auth = request.headers.get("authorization") or ""
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            try:
                subject = extract_subject_from_token(token)
                return f"user:{subject}"
            except Exception:  # noqa: BLE001 — intentional catch-all, see docstring
                # Malformed/expired token: still rate-limit by IP, don't 500.
                logger.debug("user_or_ip_key: token decode failed, falling back to IP")
    return ip_key(request)
