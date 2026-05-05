"""Integration tests for /imports/upload and /telegram/bot/upload (Этап 0.2 Шаг 3).

These complement the unit tests in test_upload_validator.py by exercising the
full route → helper → validator → service path. The service is monkey-patched
to a no-op so we test the validation gate in isolation, without bringing up
extractors / DB-side ImportSession persistence.

Three categories:
  - happy path (CSV / PDF / XLSX / 1-line CSV) → 201,
  - rejection paths (size, mismatch, unknown, empty, zip-bomb) → 413/415 with
    structured payloads (`code`, `max_size_mb`, `actual_decompressed_mb` …),
  - cleanup invariant — `await file.close()` runs even on validation failure.

We don't bootstrap `app.main:app` because it triggers Postgres-dependent
startup events. Instead we mount the two routers on a fresh FastAPI with
dependency overrides for `get_db`, `get_current_user`, and `require_bot_token`.
"""
from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.imports import router as imports_router
from app.api.v1.telegram import require_bot_token, router as telegram_router
from app.core.config import settings


PDF_HEAD = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"


def _mb(n: float) -> int:
    return int(n * 1024 * 1024)


def _make_xlsx_zip(*, decompressed_size: int = 0, include_workbook: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if include_workbook:
            payload = b"x" * decompressed_size if decompressed_size else b"<workbook/>"
            archive.writestr("xl/workbook.xml", payload)
        else:
            archive.writestr("not-a-workbook.txt", b"hello")
    return buffer.getvalue()


class _FakeUser:
    id = 1
    is_active = True
    email = "test@example.com"
    telegram_id = 555
    full_name = None


class _FakeService:
    """Records what reached the service layer so each test can assert routing."""

    last_call: dict[str, Any] = {}

    def __init__(self, db):
        self.db = db

    def upload_source(self, *, user_id, filename, raw_bytes, delimiter, force_new=False):
        # `force_new` added in Этап 0.5 — accept it so the route can pass it
        # through; not asserted because validation tests are about the
        # 413/415 boundary, not duplicate-detection.
        _FakeService.last_call = {
            "user_id": user_id,
            "filename": filename,
            "raw_bytes_len": len(raw_bytes),
            "delimiter": delimiter,
            "force_new": force_new,
        }
        return {
            "session_id": 1,
            "filename": filename,
            "source_type": "csv",
            "status": "analyzed",
            "detected_columns": [],
            "sample_rows": [],
            "total_rows": 0,
        }


@pytest.fixture
def app(monkeypatch):
    # Patch ImportService BEFORE the route imports it on first request — both
    # routers do `from app.services.import_service import ImportService` at
    # module import time, so we override in-place.
    import app.api.v1.imports as imports_module
    import app.api.v1.telegram as telegram_module

    monkeypatch.setattr(imports_module, "ImportService", _FakeService)
    monkeypatch.setattr(telegram_module, "ImportService", _FakeService)

    fake_user = _FakeUser()

    def _fake_db():
        # Imports/telegram routers don't actually query the DB on the upload
        # path because we stubbed ImportService, but `get_db` is wired through
        # FastAPI's Depends and must be satisfied. A None placeholder is fine
        # — _FakeService accepts whatever `db` it gets.
        yield None

    def _fake_current_user():
        return fake_user

    def _fake_bot_token():
        return None

    test_app = FastAPI()
    test_app.include_router(imports_router)
    test_app.include_router(telegram_router)
    test_app.dependency_overrides[get_db] = _fake_db
    test_app.dependency_overrides[get_current_user] = _fake_current_user
    test_app.dependency_overrides[require_bot_token] = _fake_bot_token

    # Telegram bot upload also resolves a User via direct ORM. Stub the call
    # so the route doesn't reach a real session.
    def _fake_query(_model):
        class _Q:
            def filter(self, *_a, **_kw): return self
            def first(self): return fake_user
        return _Q()

    class _DummySession:
        def query(self, model): return _fake_query(model)
        def rollback(self): pass

    def _fake_db_for_telegram():
        yield _DummySession()

    # The two routers share `get_db`; the telegram bot path needs `query`,
    # so override the dependency for the whole app to a session that handles both.
    test_app.dependency_overrides[get_db] = _fake_db_for_telegram

    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


# ─── happy path ───────────────────────────────────────────────────────────────


def test_upload_csv_within_limit_succeeds(client):
    body = b"date,amount,description\n2026-01-01,100.00,Coffee\n" * 50
    response = client.post(
        "/imports/upload",
        files={"file": ("statement.csv", body, "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert _FakeService.last_call["raw_bytes_len"] == len(body)


def test_upload_pdf_within_limit_succeeds(client):
    body = PDF_HEAD + b"\n" + b"a" * (_mb(1) - len(PDF_HEAD) - 1)
    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", body, "application/pdf")},
    )
    assert response.status_code == 201, response.text


def test_upload_xlsx_within_limit_succeeds(client):
    body = _make_xlsx_zip()
    response = client.post(
        "/imports/upload",
        files={"file": (
            "statement.xlsx",
            body,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert response.status_code == 201, response.text


def test_upload_short_csv_one_transaction_succeeds(client):
    """Regression: a ~50-byte CSV must clear the 95% printable threshold."""
    body = b"date,amount\n2026-01-01,100"
    response = client.post(
        "/imports/upload",
        files={"file": ("tiny.csv", body, "text/csv")},
    )
    assert response.status_code == 201, response.text


# ─── size limits ──────────────────────────────────────────────────────────────


def test_upload_pdf_over_limit_returns_413_with_payload(client):
    cap = settings.MAX_UPLOAD_SIZE_PDF_MB
    body = PDF_HEAD + b"a" * (_mb(cap) - len(PDF_HEAD) + 100)
    response = client.post(
        "/imports/upload",
        files={"file": ("big.pdf", body, "application/pdf")},
    )
    assert response.status_code == 413
    payload = response.json()
    assert payload["code"] == "upload_too_large"
    assert payload["max_size_mb"] == cap
    assert payload["actual_size_mb"] >= cap
    assert payload["kind"] == "pdf"


def test_upload_csv_over_limit_returns_413(client):
    cap = settings.MAX_UPLOAD_SIZE_CSV_MB
    body = b"date,amount\n" + b"a" * (_mb(cap) + 100)
    response = client.post(
        "/imports/upload",
        files={"file": ("big.csv", body, "text/csv")},
    )
    assert response.status_code == 413
    assert response.json()["kind"] == "csv"


def test_upload_xlsx_over_limit_returns_413(client):
    """An XLSX whose ON-DISK size exceeds the 10 MB cap is rejected before
    the deep ZIP-bomb check even runs."""
    cap = settings.MAX_UPLOAD_SIZE_XLSX_MB
    # Use STORED (no compression) so a payload above 10 MB stays above 10 MB
    # in the resulting archive.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("xl/workbook.xml", b"x" * (_mb(cap) + _mb(2)))
    body = buffer.getvalue()
    assert len(body) > _mb(cap)

    response = client.post(
        "/imports/upload",
        files={"file": (
            "big.xlsx",
            body,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert response.status_code == 413
    assert response.json()["kind"] == "xlsx"


# ─── type mismatch ────────────────────────────────────────────────────────────


def test_upload_pdf_extension_with_csv_bytes_returns_415(client):
    body = b"date,amount\n2026-01-01,100\n" * 100
    response = client.post(
        "/imports/upload",
        files={"file": ("statement.pdf", body, "application/pdf")},
    )
    assert response.status_code == 415
    payload = response.json()
    # CSV negative-check passes, then declared=pdf vs detected=csv → mismatch.
    assert payload["code"] == "extension_content_mismatch"


def test_upload_csv_extension_with_pdf_bytes_returns_415(client):
    body = PDF_HEAD + b"more pdf body"
    response = client.post(
        "/imports/upload",
        files={"file": ("statement.csv", body, "text/csv")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "extension_content_mismatch"


def test_upload_unknown_extension_returns_415(client):
    body = b"\x89\x00binary\x00garbage" * 10
    response = client.post(
        "/imports/upload",
        files={"file": ("weird.bin", body, "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_upload_type"


# ─── malformed / edge ────────────────────────────────────────────────────────


def test_upload_empty_file_returns_415(client):
    response = client.post(
        "/imports/upload",
        files={"file": ("empty.csv", b"", "text/csv")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "empty_file"


def test_upload_xlsx_zip_bomb_returns_415_with_decompression_payload(client):
    bomb_size = (settings.MAX_XLSX_DECOMPRESSED_MB + 50) * 1024 * 1024
    bomb = _make_xlsx_zip(decompressed_size=bomb_size)
    # On-disk small enough to clear the 10 MB type cap.
    assert len(bomb) < _mb(settings.MAX_UPLOAD_SIZE_XLSX_MB)

    response = client.post(
        "/imports/upload",
        files={"file": (
            "bomb.xlsx",
            bomb,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )},
    )
    assert response.status_code == 415
    payload = response.json()
    assert payload["code"] == "xlsx_decompression_too_large"
    assert payload["max_decompressed_mb"] == settings.MAX_XLSX_DECOMPRESSED_MB
    assert payload["actual_decompressed_mb"] > settings.MAX_XLSX_DECOMPRESSED_MB


# ─── cleanup invariant ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upload_does_not_leak_file_handle_on_validation_error():
    """Direct call into the helper — TestClient hides the UploadFile object,
    so we go one level down to assert `await file.close()` was awaited even
    on a 415 path."""
    from fastapi import UploadFile
    from app.api.v1._upload_helpers import validate_and_read_upload
    from app.services.upload_validator import UnsupportedUploadTypeError

    upload = UploadFile(filename="weird.bin", file=io.BytesIO(b"\x89\x00garbage" * 50))
    upload.close = AsyncMock(wraps=upload.close)  # type: ignore[method-assign]

    with pytest.raises(UnsupportedUploadTypeError):
        await validate_and_read_upload(upload)

    upload.close.assert_awaited()


# ─── telegram bot route — same validation contract ──────────────────────────


def test_telegram_bot_upload_applies_same_validation(client):
    cap = settings.MAX_UPLOAD_SIZE_PDF_MB
    body = PDF_HEAD + b"a" * (_mb(cap) + 100)
    response = client.post(
        "/telegram/bot/upload",
        data={"telegram_id": "555", "delimiter": ","},
        files={"file": ("big.pdf", body, "application/pdf")},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"
    assert response.json()["kind"] == "pdf"


def test_telegram_bot_upload_happy_path(client):
    body = b"date,amount\n2026-01-01,100\n" * 20
    response = client.post(
        "/telegram/bot/upload",
        data={"telegram_id": "555", "delimiter": ","},
        files={"file": ("statement.csv", body, "text/csv")},
    )
    assert response.status_code == 201


# ─── extra coverage: no-extension fallback + bot auth boundary ──────────────


def test_upload_no_extension_falls_back_to_magic_detection(client):
    """Filename without an extension (e.g. file forwarded through Telegram)
    must NOT fail the validator outright — it falls back to magic-byte
    detection. PDF magic should be recognized and accepted."""
    body = PDF_HEAD + b"\n" + b"a" * (_mb(1) - len(PDF_HEAD) - 1)
    response = client.post(
        "/imports/upload",
        files={"file": ("STATEMENT", body, "application/pdf")},
    )
    assert response.status_code == 201, response.text


def test_telegram_bot_upload_requires_token(app):
    """Without `dependency_overrides[require_bot_token]`, calling the bot
    route should fail at the auth dependency BEFORE any validation runs.
    Guards against accidental relaxation of the bot-token check that would
    let an unauthenticated caller hit our upload pipeline."""
    from app.api.v1.telegram import require_bot_token
    app.dependency_overrides.pop(require_bot_token, None)
    raw_client = TestClient(app, raise_server_exceptions=False)
    response = raw_client.post(
        "/telegram/bot/upload",
        data={"telegram_id": "555", "delimiter": ","},
        files={"file": ("statement.csv", b"date,amount\n2026-01-01,100\n", "text/csv")},
    )
    # require_bot_token returns 401 when the header is missing/wrong.
    assert response.status_code == 401
