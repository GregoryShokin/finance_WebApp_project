"""Golden-dataset parametrized tests for import_normalizer_v2 (Phase 1.4).

Infrastructure only — no raw fixtures ship in the repo (see
tests/fixtures/statements/README.md). A test parameter skips when:

  - the expected file has ``status == "pending_raw_fixture"``, or
  - the corresponding raw file under ``raw/`` is missing, or
  - no raw parser is implemented for the raw file's extension yet.

When both the raw file and a non-pending expected are present, the test
runs the normalizer on each row and compares extracted tokens, skeleton,
direction and fingerprint against the expected JSON. Identifier fields in
the expected JSON are ``sha256(value)[:16]``; free-form fields (person_name,
counterparty_org) are ``"PRESENT"`` / null. See the README for the schema.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.services.import_normalizer_v2 import (
    extract_tokens,
    fingerprint as compute_fingerprint,
    normalize_skeleton,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "statements"
EXPECTED_DIR = FIXTURES_DIR / "expected"
RAW_DIR = FIXTURES_DIR / "raw"

_EXPECTED_FILES = sorted(EXPECTED_DIR.glob("*.expected.json"))


def _hash16(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _load_raw_rows(raw_path: Path) -> list[tuple[str, str]]:
    """Return list of (direction, description) for each row in a raw file.

    Dispatch by extension. Parsers are implemented lazily: when a real raw
    fixture of a new format first lands, flesh out the helper for it.
    Until then we skip with an explicit reason so the test is a no-op
    rather than a false failure. The TSV reader expects two columns
    ``direction`` and ``description`` — derive this form from bank-specific
    exports once per fixture (keep the intermediate file under ``raw/``,
    it is gitignored).
    """
    suffix = raw_path.suffix.lower()
    if suffix == ".csv":
        return _load_csv_rows(raw_path)
    pytest.skip(
        f"raw parser not implemented for {suffix} "
        f"(add a loader when the first {suffix} fixture lands)"
    )


def _load_csv_rows(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or "description" not in reader.fieldnames:
            pytest.skip(
                f"{path.name}: CSV must expose columns `direction` and "
                f"`description`; pre-process bank export into this form"
            )
        for r in reader:
            direction = (r.get("direction") or "unknown").strip() or "unknown"
            description = (r.get("description") or "").strip()
            rows.append((direction, description))
    return rows


@pytest.mark.parametrize(
    "expected_path",
    _EXPECTED_FILES,
    ids=lambda p: p.stem,
)
def test_golden_normalization(expected_path: Path) -> None:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    status = expected.get("status")
    if status == "pending_raw_fixture":
        pytest.skip(f"{expected_path.name}: status={status}")

    fixture_name = expected["fixture"]
    raw_path = RAW_DIR / fixture_name
    if not raw_path.exists():
        pytest.skip(f"raw fixture not provided: raw/{fixture_name}")

    bank = expected["bank"]
    account_id = expected.get("account_id", 0)
    raw_rows = _load_raw_rows(raw_path)

    assert expected["rows"], (
        f"{expected_path.name}: status is {status!r} but rows[] is empty — "
        f"flip back to pending_raw_fixture or populate rows"
    )

    for exp_row in expected["rows"]:
        idx = exp_row["line_index"]
        assert idx < len(raw_rows), (
            f"{expected_path.name}: expected line_index={idx} but raw has "
            f"only {len(raw_rows)} rows"
        )
        direction, description = raw_rows[idx]

        assert _hash16(description) == exp_row["raw_description_sha256"], (
            f"raw_description_sha256 mismatch at line {idx}: "
            f"expected file is out of date vs raw"
        )

        tokens = extract_tokens(description)
        skeleton = normalize_skeleton(description, tokens)

        exp_ex = exp_row["extracted"]
        assert _hash16(tokens.phone) == exp_ex["phone"], f"phone mismatch at line {idx}"
        assert _hash16(tokens.contract) == exp_ex["contract"], f"contract mismatch at line {idx}"
        assert _hash16(tokens.iban) == exp_ex["iban"], f"iban mismatch at line {idx}"
        assert _hash16(tokens.card) == exp_ex["card"], f"card mismatch at line {idx}"
        assert (
            ("PRESENT" if tokens.person_name else None) == exp_ex["person_name"]
        ), f"person_name presence mismatch at line {idx}"
        assert (
            ("PRESENT" if tokens.counterparty_org else None) == exp_ex["counterparty_org"]
        ), f"counterparty_org presence mismatch at line {idx}"
        assert len(tokens.amounts) == exp_ex["amounts_count"], f"amounts_count mismatch at line {idx}"
        assert len(tokens.dates) == exp_ex["dates_count"], f"dates_count mismatch at line {idx}"

        assert skeleton == exp_row["skeleton"], f"skeleton mismatch at line {idx}"
        assert direction == exp_row["direction"], f"direction mismatch at line {idx}"

        fp = compute_fingerprint(
            bank=bank,
            account_id=account_id,
            direction=direction,
            skeleton=skeleton,
            contract=tokens.contract,
        )
        assert fp == exp_row["fingerprint"], f"fingerprint mismatch at line {idx}"
