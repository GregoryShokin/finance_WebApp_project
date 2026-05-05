"""Tests for `app/core/client_ip.py` — the XFF resolver shared by
MaxBodySizeMiddleware (logging) and slowapi key functions (rate limiting).

The single load-bearing security invariant: an attacker connecting directly
(NOT through a trusted proxy) MUST NOT be able to set their apparent IP via
`X-Forwarded-For`. The negative test below pins this — without it a future
"refactor" that always trusts XFF silently turns rate-limit per-IP into per-
"whatever the client says".
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.requests import Request

from app.core.client_ip import _trusted_networks, get_client_ip


def _make_request(*, peer: str | None, headers: dict[str, str] | None = None) -> Request:
    """Forge a minimal ASGI scope. We bypass TestClient entirely — the unit
    we're testing only reads `request.client` and `request.headers`."""
    raw_headers = []
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode(), value.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (peer, 12345) if peer else None,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _reset_trusted_cache():
    """`_trusted_networks` is `lru_cache`d off settings — clear between tests
    that monkey-patch the setting so each test sees its own list."""
    _trusted_networks.cache_clear()
    yield
    _trusted_networks.cache_clear()


def test_falls_back_to_peer_when_no_xff_header():
    request = _make_request(peer="203.0.113.5")
    assert get_client_ip(request) == "203.0.113.5"


def test_returns_unknown_when_request_has_no_client():
    request = _make_request(peer=None)
    assert get_client_ip(request) == "unknown"


def test_xff_ignored_when_proxy_not_trusted():
    """Security invariant: untrusted peer + spoofed XFF → use peer, not XFF."""
    request = _make_request(
        peer="203.0.113.5",
        headers={"X-Forwarded-For": "1.2.3.4"},
    )
    with patch("app.core.client_ip.settings") as mock_settings:
        mock_settings.TRUSTED_PROXIES = []  # nothing trusted
        _trusted_networks.cache_clear()
        assert get_client_ip(request) == "203.0.113.5"


def test_xff_used_when_proxy_is_trusted_cidr():
    """Trusted proxy (matched by CIDR) → leftmost XFF entry is the real client."""
    request = _make_request(
        peer="10.0.0.7",
        headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.7"},
    )
    with patch("app.core.client_ip.settings") as mock_settings:
        mock_settings.TRUSTED_PROXIES = ["10.0.0.0/8"]
        _trusted_networks.cache_clear()
        assert get_client_ip(request) == "203.0.113.5"


def test_xff_used_when_proxy_is_trusted_exact_ip():
    request = _make_request(
        peer="172.16.0.1",
        headers={"X-Forwarded-For": "198.51.100.42"},
    )
    with patch("app.core.client_ip.settings") as mock_settings:
        mock_settings.TRUSTED_PROXIES = ["172.16.0.1"]
        _trusted_networks.cache_clear()
        assert get_client_ip(request) == "198.51.100.42"


def test_malformed_xff_falls_back_to_peer():
    """A non-IP first token in XFF → don't return garbage, use peer."""
    request = _make_request(
        peer="10.0.0.1",
        headers={"X-Forwarded-For": "not-an-ip, 10.0.0.1"},
    )
    with patch("app.core.client_ip.settings") as mock_settings:
        mock_settings.TRUSTED_PROXIES = ["10.0.0.0/8"]
        _trusted_networks.cache_clear()
        assert get_client_ip(request) == "10.0.0.1"


def test_malformed_trusted_proxies_entries_are_dropped_silently():
    """A typo in TRUSTED_PROXIES must not crash startup or every request —
    the bad entry is logged and ignored, valid ones still apply."""
    with patch("app.core.client_ip.settings") as mock_settings:
        mock_settings.TRUSTED_PROXIES = ["definitely-not-a-cidr", "10.0.0.0/8"]
        _trusted_networks.cache_clear()
        request = _make_request(
            peer="10.0.0.1",
            headers={"X-Forwarded-For": "203.0.113.5"},
        )
        assert get_client_ip(request) == "203.0.113.5"
