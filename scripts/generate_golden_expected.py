"""Generate an expected/*.expected.json draft from a list of raw descriptions.

Phase 1.4 of И-08. The script is a *helper* for filling the golden dataset:
it runs the normalizer on a list of descriptions and prints the expected JSON
to stdout. It NEVER writes to expected-files — redirect stdout yourself.

Usage (from repo root)::

    python -m scripts.generate_golden_expected \\
        --fixture tbank_contract_numbers.pdf \\
        --bank tbank \\
        --account-id 0 \\
        --input descriptions.tsv \\
      > tests/fixtures/statements/expected/tbank_contract_numbers.expected.json

Input format (stdin or --input)::

    <direction>\\t<description>

``direction`` is one of ``expense``, ``income``, ``unknown``. Lines without a
tab treat the full line as the description with ``direction=unknown``. Blank
lines and lines starting with ``#`` are skipped.

Output is a *draft*: review it, trim to 10–20 representative rows, then flip
``status`` from ``"draft"`` to ``"ready"`` before committing. All identifiers
(phone, contract, iban, card) are written as ``sha256(value)[:16]``; free-form
strings (person_name, counterparty_org) are written as ``"PRESENT"`` / null.
The raw description never leaves this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from app.services.import_normalizer_v2 import (
    extract_tokens,
    fingerprint as compute_fingerprint,
    normalize_skeleton,
)


_VALID_DIRECTIONS = frozenset({"expense", "income", "unknown"})


@dataclass(frozen=True)
class InputRow:
    direction: str
    description: str


def parse_input_lines(lines: Iterable[str]) -> list[InputRow]:
    """Parse TSV-ish input into structured rows. See module docstring for format."""
    rows: list[InputRow] = []
    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" in line:
            direction, _, description = line.partition("\t")
            direction = direction.strip() or "unknown"
        else:
            direction, description = "unknown", line
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(
                f"invalid direction {direction!r}; "
                f"expected one of {sorted(_VALID_DIRECTIONS)}"
            )
        rows.append(InputRow(direction=direction, description=description))
    return rows


def _hash16(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def generate_expected(
    *,
    fixture: str,
    bank: str,
    account_id: int,
    rows: list[InputRow],
    description: str | None = None,
) -> dict:
    """Build the expected-JSON dict from parsed input rows. Pure — no I/O."""
    out_rows: list[dict] = []
    for idx, row in enumerate(rows):
        tokens = extract_tokens(row.description)
        skeleton = normalize_skeleton(row.description, tokens)
        fp = compute_fingerprint(
            bank=bank,
            account_id=account_id,
            direction=row.direction,
            skeleton=skeleton,
            contract=tokens.contract,
        )
        out_rows.append({
            "line_index": idx,
            "raw_description_sha256": _hash16(row.description),
            "direction": row.direction,
            "extracted": {
                "phone": _hash16(tokens.phone),
                "contract": _hash16(tokens.contract),
                "iban": _hash16(tokens.iban),
                "card": _hash16(tokens.card),
                "person_name": "PRESENT" if tokens.person_name else None,
                "counterparty_org": "PRESENT" if tokens.counterparty_org else None,
                "amounts_count": len(tokens.amounts),
                "dates_count": len(tokens.dates),
            },
            "skeleton": skeleton,
            "fingerprint": fp,
        })
    payload: dict = {
        "fixture": fixture,
        "bank": bank,
        "account_id": account_id,
        "status": "draft",
    }
    if description is not None:
        payload["description"] = description
    payload["rows"] = out_rows
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--fixture", required=True,
        help="Fixture filename (e.g. tbank_contract_numbers.pdf).",
    )
    parser.add_argument(
        "--bank", required=True,
        help="Bank code for fingerprint basis (e.g. tbank).",
    )
    parser.add_argument(
        "--account-id", type=int, default=0,
        help="Account id for fingerprint basis (default 0).",
    )
    parser.add_argument(
        "--description", default=None,
        help="Optional human-readable fixture description.",
    )
    parser.add_argument(
        "--input", type=Path, default=None,
        help="Path to TSV input. Defaults to stdin.",
    )
    args = parser.parse_args(argv)

    stream: TextIO
    if args.input is None:
        stream = sys.stdin
        close_after = False
    else:
        stream = args.input.open("r", encoding="utf-8")
        close_after = True

    try:
        rows = parse_input_lines(stream)
    finally:
        if close_after:
            stream.close()

    payload = generate_expected(
        fixture=args.fixture,
        bank=args.bank,
        account_id=args.account_id,
        rows=rows,
        description=args.description,
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2, sort_keys=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
