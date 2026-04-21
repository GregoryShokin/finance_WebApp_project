"""Integration tests for Phase 1.3: v2 normalization wired into ImportService.

Verifies the v2 step is additive (v1 keys survive), fingerprint-cluster
invariant holds end-to-end, and any failure in v2 is swallowed without
breaking row processing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

# Importing ImportService triggers app.services.import_extractors.__init__,
# which unconditionally imports pdf_extractor → pypdf at module load. Skip
# here when pypdf isn't installed locally; Docker/CI always has it.
pytest.importorskip("pypdf")

from app.services.import_service import ImportService


def _session(**overrides):
    """Minimal ImportSession stand-in (duck-typed; we only touch source_type)."""
    return SimpleNamespace(id=1, source_type="tbank", **overrides)


def test_v2_adds_expected_keys_preserving_v1() -> None:
    v1 = {
        "description": "Оплата по договору №7001 от Иванов И.И. 500,00 руб",
        "import_original_description": "Оплата по договору №7001 от Иванов И.И. 500,00 руб",
        "amount": "500.00",
        "type": "expense",
        "account_id": 42,
        "category_id": 7,  # untouched
    }

    out = ImportService._apply_v2_normalization(
        normalized=dict(v1),
        session=_session(),
        fallback_account_id=42,
        row_index=1,
    )

    # v2 keys present
    assert out["normalizer_version"] == 2
    assert "<CONTRACT>" in out["skeleton"]
    assert "<PERSON>" in out["skeleton"]
    assert isinstance(out["fingerprint"], str) and len(out["fingerprint"]) == 16
    assert out["tokens"]["contract"] == "7001"
    assert out["tokens"]["person_name_present"] is True

    # v1 keys intact
    assert out["description"] == v1["description"]
    assert out["amount"] == "500.00"
    assert out["type"] == "expense"
    assert out["account_id"] == 42
    assert out["category_id"] == 7


def test_v2_fingerprint_stable_for_cluster_mates() -> None:
    # Same bank + account + direction + skeleton + contract → same fingerprint.
    session = _session()
    base = {"type": "income", "account_id": 42}

    row_a = {
        **base,
        "description": "Перевод по договору №9001 от Иванов И.И. 1 000,00 руб 15.03.2026",
        "import_original_description": "Перевод по договору №9001 от Иванов И.И. 1 000,00 руб 15.03.2026",
    }
    row_b = {
        **base,
        "description": "Перевод по договору №9001 от Петров П.П. 2 500,00 руб 20.03.2026",
        "import_original_description": "Перевод по договору №9001 от Петров П.П. 2 500,00 руб 20.03.2026",
    }
    row_c = {
        **base,
        "description": "Перевод по договору №9002 от Иванов И.И. 1 000,00 руб 15.03.2026",
        "import_original_description": "Перевод по договору №9002 от Иванов И.И. 1 000,00 руб 15.03.2026",
    }

    out_a = ImportService._apply_v2_normalization(dict(row_a), session, 42, 1)
    out_b = ImportService._apply_v2_normalization(dict(row_b), session, 42, 2)
    out_c = ImportService._apply_v2_normalization(dict(row_c), session, 42, 3)

    assert out_a["fingerprint"] == out_b["fingerprint"]  # same contract → same cluster
    assert out_a["fingerprint"] != out_c["fingerprint"]  # different contract → different cluster


def test_v2_unknown_bank_when_source_type_missing() -> None:
    session = SimpleNamespace(id=1, source_type=None)
    out = ImportService._apply_v2_normalization(
        normalized={"description": "x", "type": "expense", "account_id": 1},
        session=session,
        fallback_account_id=1,
        row_index=1,
    )
    # Still produces a fingerprint; "unknown" was substituted for the bank.
    assert isinstance(out["fingerprint"], str) and len(out["fingerprint"]) == 16


def test_v2_unknown_direction_differs_from_expense() -> None:
    # When direction isn't determined yet, we record it as "unknown" rather
    # than defaulting to "expense". That way correcting the type later produces
    # a visibly different fingerprint instead of a silent drift.
    session = _session()
    row_no_dir = {
        "description": "Оплата в Пятёрочке 500,00 руб",
        "account_id": 42,
    }
    row_expense = {**row_no_dir, "type": "expense"}

    out_unknown = ImportService._apply_v2_normalization(
        dict(row_no_dir), session, 42, 1,
    )
    out_expense = ImportService._apply_v2_normalization(
        dict(row_expense), session, 42, 2,
    )

    assert out_unknown["fingerprint"] != out_expense["fingerprint"]


def test_v2_failure_does_not_break_row(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force extract_tokens to raise. The row should come back with v1 keys
    # intact and no v2 keys added.
    def boom(_description: str):
        raise RuntimeError("synthetic normalizer failure")

    monkeypatch.setattr(
        "app.services.import_service.v2_extract_tokens", boom
    )

    original = {
        "description": "Покупка",
        "amount": "100.00",
        "type": "expense",
        "account_id": 42,
    }
    out = ImportService._apply_v2_normalization(
        normalized=dict(original),
        session=_session(),
        fallback_account_id=42,
        row_index=1,
    )

    # v1 untouched
    assert out == original
    # v2 keys absent
    assert "skeleton" not in out
    assert "fingerprint" not in out
    assert "normalizer_version" not in out
