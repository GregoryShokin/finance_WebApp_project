"""Tests for `/api/v1/_test/*` endpoints.

The endpoints themselves are tooling for the e2e Playwright suite — these
tests verify the THREE-LAYER DEFENCE around them, not the seed logic itself
(that's covered transitively when the e2e suite runs against them).

What this file proves:

1. ``ENABLE_TEST_ENDPOINTS=False`` → every endpoint returns 404 (Layer 1: the
   router is not even registered, so the route truly doesn't exist).
2. ``ENABLE_TEST_ENDPOINTS=True`` + ``APP_ENV=prod`` → ``main.py`` refuses to
   instantiate the app with a clear RuntimeError (Layer 3).
3. The Layer-2 guard in test_utils.py independently returns 404 when the flag
   is False, even if a future refactor wires the router unconditionally
   (we test the dependency function directly).
4. ``seed_bank`` is genuinely UPSERT-on-name with the contract documented in
   §5 — second call returns ``created=False`` and reports the previous status.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


_TEST_PATHS = (
    "/api/v1/_test/seed/user",
    "/api/v1/_test/seed/bank",
    "/api/v1/_test/seed/account",
    "/api/v1/_test/cleanup/user",
    "/api/v1/_test/reset/rate-limit",
    "/api/v1/_test/auth/issue-tokens",
    "/api/v1/_test/import-session/1",
)


def _build_app(monkeypatch, *, enabled: bool, env: str = "dev"):
    """Reload `app.main` with overridden settings so the router-include branch
    sees the flag we set, not the live `.env` value.
    """
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "APP_ENV", env)
    monkeypatch.setattr(config_module.settings, "ENABLE_TEST_ENDPOINTS", enabled)
    # is_production is a cached_property — bust it.
    config_module.settings.__dict__.pop("is_production", None)

    import app.main as main_module
    importlib.reload(main_module)
    return main_module.app


def test_layer1_router_absent_when_flag_false(monkeypatch):
    app = _build_app(monkeypatch, enabled=False)
    client = TestClient(app, base_url="http://localhost")
    for path in _TEST_PATHS:
        if path.startswith("/api/v1/_test/import-session/"):
            resp = client.get(path)
        else:
            resp = client.post(path, json={})
        assert resp.status_code == 404, (
            f"Layer 1 leaked: {path} returned {resp.status_code} "
            f"with ENABLE_TEST_ENDPOINTS=False — router must not be registered."
        )


def test_layer2_dependency_returns_404_when_flag_false(monkeypatch):
    """Even if a refactor includes the router unconditionally, the per-route
    Depends(require_test_endpoints_enabled) raises 404 first.
    """
    from app.core import config as config_module
    from app.api.v1.test_utils import require_test_endpoints_enabled

    monkeypatch.setattr(config_module.settings, "ENABLE_TEST_ENDPOINTS", False)
    with pytest.raises(HTTPException) as excinfo:
        require_test_endpoints_enabled()
    assert excinfo.value.status_code == 404


def test_layer2_dependency_passes_when_flag_true(monkeypatch):
    from app.core import config as config_module
    from app.api.v1.test_utils import require_test_endpoints_enabled

    monkeypatch.setattr(config_module.settings, "ENABLE_TEST_ENDPOINTS", True)
    require_test_endpoints_enabled()  # must not raise


def test_layer3_app_refuses_to_start_in_production(monkeypatch):
    """If someone deploys with ENABLE_TEST_ENDPOINTS=true AND APP_ENV=prod,
    the import of app.main raises RuntimeError. This is the last-ditch guard.
    """
    with pytest.raises(RuntimeError, match="ENABLE_TEST_ENDPOINTS"):
        _build_app(monkeypatch, enabled=True, env="prod")


def test_layer3_production_with_flag_false_starts_fine(monkeypatch):
    app = _build_app(monkeypatch, enabled=False, env="prod")
    client = TestClient(app, base_url="http://localhost")
    # Sanity: /health still works in production-mode boot.
    assert client.get("/api/v1/health").status_code == 200


def test_seed_bank_upsert_contract(monkeypatch, db):
    """seed_bank is the contract that Phase 6 (bank guard) depends on:
    second call with the same name updates extractor_status and reports
    the previous one. Without this, teardown can't restore Сбер.
    """
    from app.api.v1.test_utils import seed_bank, SeedBankRequest

    first = seed_bank(SeedBankRequest(name="ТестБанк", extractor_status="supported"), db)
    assert first.created is True
    assert first.previous_extractor_status is None
    assert first.extractor_status == "supported"

    second = seed_bank(SeedBankRequest(name="ТестБанк", extractor_status="pending"), db)
    assert second.created is False
    assert second.bank_id == first.bank_id
    assert second.previous_extractor_status == "supported"
    assert second.extractor_status == "pending"
