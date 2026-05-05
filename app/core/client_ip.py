"""Client-IP resolution honoring trusted reverse proxies.

Why this exists in one helper, not duplicated per call site:
  - `MaxBodySizeMiddleware` logs the offender's IP for security telemetry
    (Этап 0.2),
  - `slowapi` key functions need the real IP for per-IP rate limits
    (Этап 0.3),
  - both must agree on what "client IP" means. If middleware sees the proxy
    and slowapi sees the spoofed `X-Forwarded-For`, security is desynced.

`X-Forwarded-For` is trusted ONLY when the immediate peer (`request.client.host`)
matches an entry in `settings.TRUSTED_PROXIES` (CIDR-aware via ipaddress).
Otherwise an attacker connecting directly could supply any header value and
look like every IP in the world to our rate limiter.
"""
from __future__ import annotations

import ipaddress
import logging
from functools import lru_cache

from starlette.requests import Request

from app.core.config import settings


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _trusted_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse `TRUSTED_PROXIES` once. Entries can be plain IPs (`10.0.0.1`)
    or CIDR ranges (`10.0.0.0/8`); both lower into networks via `ip_network(strict=False)`.
    Malformed entries are dropped with a warning so a typo doesn't crash startup."""
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in settings.TRUSTED_PROXIES or []:
        candidate = str(raw).strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXIES: ignoring malformed entry %r", candidate)
    return tuple(networks)


def _is_trusted_peer(peer_host: str) -> bool:
    if not _trusted_networks():
        return False
    try:
        peer = ipaddress.ip_address(peer_host)
    except ValueError:
        return False
    return any(peer in network for network in _trusted_networks())


def _first_xff_ip(header_value: str) -> str | None:
    # XFF is "client, proxy1, proxy2, ..." — the leftmost token is the
    # original client per RFC 7239 (and de-facto). Strip + validate.
    for token in header_value.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            return None
        return candidate
    return None


def get_client_ip(request: Request) -> str:
    """Best-effort client IP.

    Trust hierarchy:
      1. If the immediate peer is in `TRUSTED_PROXIES` AND a valid
         `X-Forwarded-For` is present, use the leftmost XFF entry.
      2. Otherwise, return `request.client.host`.
      3. If the request has no client (rare in tests / unusual transports),
         return the literal "unknown" rather than raising — callers use this
         purely for logging/keying, never for authorization.
    """
    peer_host = request.client.host if request.client else None
    if peer_host and _is_trusted_peer(peer_host):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            candidate = _first_xff_ip(xff)
            if candidate:
                return candidate
    return peer_host or "unknown"
