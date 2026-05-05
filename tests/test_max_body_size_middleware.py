"""Tests for MaxBodySizeMiddleware (Этап 0.2).

Header-only check, by design (see middleware docstring). The middleware never
reads body bytes — that's the route's job via `read_upload_with_limits`. So
these tests construct requests with explicit `Content-Length` headers and
confirm the middleware either short-circuits to 413 or passes through to the
inner app.

Each test mounts the middleware on a fresh minimal FastAPI app. We don't
bootstrap `app.main:app` here — it triggers Postgres-dependent startup events
(`BankService.ensure_extractor_status_baseline`) that have no place in a unit
test for a generic middleware.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.middleware import MaxBodySizeMiddleware


# Picked up from config so changes to GLOBAL_BODY_SIZE_CAP_MB don't silently
# decouple production behavior from what these tests assert.
CAP_MB = settings.GLOBAL_BODY_SIZE_CAP_MB
CAP_BYTES = CAP_MB * 1024 * 1024


def _build_app(*, max_size_mb: int = CAP_MB) -> FastAPI:
    inner = FastAPI()

    @inner.get("/")
    def _root():
        return {"ok": True}

    @inner.post("/echo")
    async def _echo():
        return {"ok": True}

    inner.add_middleware(MaxBodySizeMiddleware, max_size_mb=max_size_mb)
    return inner


@pytest.fixture
def client():
    return TestClient(_build_app())


def test_global_cap_middleware_rejects_oversized_via_content_length(client):
    response = client.post(
        "/echo",
        content=b"",  # body irrelevant — header is what we test
        headers={"Content-Length": str(CAP_BYTES + 5_000_000)},
    )
    assert response.status_code == 413
    payload = response.json()
    assert payload["code"] == "global_body_size_exceeded"
    assert payload["max_size_mb"] == CAP_MB
    assert payload["actual_size_mb"] > CAP_MB


def test_global_cap_middleware_passes_request_within_cap(client):
    # 5 MB declared, well under 30 MB cap → middleware passes; route returns 200.
    body = b"x" * (5 * 1024 * 1024)
    response = client.post("/echo", content=body)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_global_cap_middleware_passes_without_content_length_header(client):
    # Variant A confirmed: no Content-Length → don't block; route-streaming
    # is the line of defense. We force the missing header by sending an
    # iterable body, which triggers chunked encoding.
    def _chunks():
        yield b"hello"

    response = client.post("/echo", content=_chunks())
    assert response.status_code == 200


def test_global_cap_middleware_passes_at_exact_cap(client):
    # `>` not `>=`: exactly at the cap is allowed. Pure header test, no body.
    response = client.post(
        "/echo",
        content=b"",
        headers={"Content-Length": str(CAP_BYTES)},
    )
    assert response.status_code == 200


def test_global_cap_middleware_rejects_one_byte_over_cap(client):
    response = client.post(
        "/echo",
        content=b"",
        headers={"Content-Length": str(CAP_BYTES + 1)},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "global_body_size_exceeded"


def test_global_cap_middleware_passes_get_request(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_global_cap_middleware_handles_malformed_content_length(client):
    # Starlette's TestClient doesn't let us send a literal "not_a_number" header
    # easily — it normalizes ints. We test the middleware's int(raw) path
    # directly through a unit-style call instead.
    from starlette.requests import Request

    middleware = MaxBodySizeMiddleware(_build_app(), max_size_mb=CAP_MB)

    async def _fake_call_next(_request):
        from starlette.responses import JSONResponse
        return JSONResponse({"ok": True})

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/echo",
        "headers": [(b"content-length", b"not-a-number")],
        "client": ("127.0.0.1", 1234),
        "url": "http://testserver/echo",
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
    }
    request = Request(scope)
    import asyncio
    response = asyncio.get_event_loop().run_until_complete(
        middleware.dispatch(request, _fake_call_next),
    )
    # Malformed → treat as missing → pass through.
    assert response.status_code == 200


def test_global_cap_middleware_handles_negative_content_length(client):
    # Nonsensical but parseable as int. Middleware must NOT compare it to the
    # cap (-1 < cap, would falsely "pass") — instead, treat as missing and let
    # downstream layers reject if they want to. The route-streaming check is
    # still active for the actual body.
    response = client.post(
        "/echo",
        content=b"",
        headers={"Content-Length": "-1"},
    )
    # Either 200 (fall-through) or whatever Starlette/uvicorn returns for the
    # malformed header; the contract we care about is "NOT 413 from us".
    assert response.status_code != 413


def test_global_cap_middleware_response_includes_actual_size(client):
    # Guards the JSON contract: frontend will read max_size_mb / actual_size_mb
    # to render an actionable error. Round-tripping through json.loads
    # confirms both fields are present and numeric.
    declared = CAP_BYTES + 17 * 1024 * 1024
    response = client.post(
        "/echo",
        content=b"",
        headers={"Content-Length": str(declared)},
    )
    assert response.status_code == 413
    payload = json.loads(response.content)
    assert isinstance(payload["max_size_mb"], int)
    assert isinstance(payload["actual_size_mb"], (int, float))
    assert payload["actual_size_mb"] == round(declared / 1024 / 1024, 2)
