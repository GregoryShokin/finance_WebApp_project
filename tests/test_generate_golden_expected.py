"""Unit tests for scripts.generate_golden_expected (Phase 1.4 infra).

Exercises the pure entry points on synthetic input only — no raw fixture
required, no subprocess. The script itself is tested via the same helpers
the CLI uses (``parse_input_lines`` + ``generate_expected``).
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest

from scripts.generate_golden_expected import (
    InputRow,
    generate_expected,
    main,
    parse_input_lines,
)


def _hash16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# parse_input_lines
# ---------------------------------------------------------------------------


def test_parse_input_lines_handles_tsv_and_plain_and_comments() -> None:
    lines = [
        "# comment, ignored\n",
        "\n",
        "expense\tПеревод по договору №1234567\n",
        "income\tЗачисление от +79161234567\n",
        "Без направления\n",
    ]
    rows = parse_input_lines(lines)
    assert rows == [
        InputRow("expense", "Перевод по договору №1234567"),
        InputRow("income", "Зачисление от +79161234567"),
        InputRow("unknown", "Без направления"),
    ]


def test_parse_input_lines_rejects_invalid_direction() -> None:
    with pytest.raises(ValueError):
        parse_input_lines(["bogus\tsome description\n"])


# ---------------------------------------------------------------------------
# generate_expected
# ---------------------------------------------------------------------------


def test_generate_expected_schema_and_token_extraction() -> None:
    desc_a = "Перевод по договору №1234567 на +79161234567"
    desc_b = "Оплата по договору №1234567 за услуги"
    rows = [
        InputRow("expense", desc_a),
        InputRow("expense", desc_b),
    ]
    payload = generate_expected(
        fixture="synthetic.csv",
        bank="synthbank",
        account_id=42,
        rows=rows,
        description="synthetic unit-test input",
    )

    assert payload["fixture"] == "synthetic.csv"
    assert payload["bank"] == "synthbank"
    assert payload["account_id"] == 42
    assert payload["status"] == "draft"
    assert payload["description"] == "synthetic unit-test input"
    assert len(payload["rows"]) == 2

    r0, r1 = payload["rows"]

    # line_index + direction are echoed.
    assert r0["line_index"] == 0 and r0["direction"] == "expense"
    assert r1["line_index"] == 1 and r1["direction"] == "expense"

    # raw description hashed, not leaked.
    assert r0["raw_description_sha256"] == _hash16(desc_a)
    assert r1["raw_description_sha256"] == _hash16(desc_b)
    assert desc_a not in json.dumps(payload, ensure_ascii=False)

    # Identifiers are sha16-hashed.
    assert r0["extracted"]["phone"] == _hash16("+79161234567")
    assert r0["extracted"]["contract"] == _hash16("1234567")
    assert r1["extracted"]["phone"] is None
    assert r0["extracted"]["contract"] == r1["extracted"]["contract"]

    # Placeholders land in skeleton; identifiers don't.
    assert "<PHONE>" in r0["skeleton"] and "+79161234567" not in r0["skeleton"]
    assert "<CONTRACT>" in r0["skeleton"] and "1234567" not in r0["skeleton"]

    # Two rows, same contract, different text → different fingerprints.
    assert r0["fingerprint"] != r1["fingerprint"]
    assert len(r0["fingerprint"]) == 16


def test_generate_expected_person_name_stays_as_presence_flag() -> None:
    rows = [InputRow("expense", "Перевод Иванов Иван Иванович")]
    payload = generate_expected(
        fixture="synthetic.csv",
        bank="synthbank",
        account_id=0,
        rows=rows,
    )
    assert payload["rows"][0]["extracted"]["person_name"] == "PRESENT"
    # No name leakage in the serialized payload.
    assert "Иванов" not in json.dumps(payload, ensure_ascii=False)


def test_generate_expected_without_description_omits_field() -> None:
    payload = generate_expected(
        fixture="synthetic.csv",
        bank="synthbank",
        account_id=0,
        rows=[InputRow("unknown", "Покупка")],
    )
    assert "description" not in payload


# ---------------------------------------------------------------------------
# main (CLI) — reading from stdin, writing to stdout
# ---------------------------------------------------------------------------


def test_main_reads_stdin_and_writes_json_to_stdout(monkeypatch, capsys) -> None:
    stdin = io.StringIO("expense\tПокупка 100,00\n")
    monkeypatch.setattr("sys.stdin", stdin)
    rc = main([
        "--fixture", "synthetic.csv",
        "--bank", "synthbank",
        "--account-id", "0",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["fixture"] == "synthetic.csv"
    assert payload["status"] == "draft"
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["direction"] == "expense"
