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
    """Minimal ImportSession stand-in — duck-typed for _apply_v2_normalization.

    The method touches `source_type` and `mapping_json` (for bank_code override).
    Everything else is irrelevant here.
    """
    defaults = {"id": 1, "source_type": "tbank", "mapping_json": {}}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


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
    session = SimpleNamespace(id=1, source_type=None, mapping_json={})
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


def test_v2_transfer_by_phone_splits_cluster_by_recipient() -> None:
    """Phase И-08 Этап 1: transfer rows to different phones → different fp.

    Regression: before transfer-aware fingerprinting, the phone was swallowed
    by the <PHONE> placeholder and all "Внешний перевод по номеру телефона"
    rows collapsed into one mega-cluster. Now each recipient stands alone.
    """
    session = _session()
    row_a = {
        "description": "Внешний перевод по номеру телефона +79161111111",
        "type": "expense",
        "account_id": 42,
    }
    row_b = {
        "description": "Внешний перевод по номеру телефона +79162222222",
        "type": "expense",
        "account_id": 42,
    }

    out_a = ImportService._apply_v2_normalization(dict(row_a), session, 42, 1)
    out_b = ImportService._apply_v2_normalization(dict(row_b), session, 42, 2)

    # Different recipients → different clusters.
    assert out_a["fingerprint"] != out_b["fingerprint"]


def test_v2_transfer_by_phone_differs_from_merchant_payment_to_same_phone() -> None:
    """A transfer TO a phone and a merchant payment mentioning the same phone
    must end up in different clusters, even though both carry the same phone.

    Merchant payments are not transfer-like → identifier does not feed into
    the fingerprint; it's masked by <PHONE>. Transfer rows feed the phone in
    raw form. Different payloads → different fingerprints.
    """
    session = _session()
    transfer = {
        "description": "Внешний перевод по номеру телефона +79161234567",
        "type": "expense",
        "account_id": 42,
    }
    merchant = {
        # Same phone number appears but this is a merchant payment, not a transfer.
        "description": "Оплата Megafon +79161234567 Volgodonsk RUS",
        "type": "expense",
        "account_id": 42,
    }

    out_transfer = ImportService._apply_v2_normalization(dict(transfer), session, 42, 1)
    out_merchant = ImportService._apply_v2_normalization(dict(merchant), session, 42, 2)

    assert out_transfer["fingerprint"] != out_merchant["fingerprint"]


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
