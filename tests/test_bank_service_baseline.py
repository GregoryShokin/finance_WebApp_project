"""Tests for BankService.ensure_extractor_status_baseline (Этап 1 MVP launch).

Five scenarios per the plan:
  1. Fresh state (all 'pending') → 4 supported codes get promoted.
  2. Bank not in whitelist stays 'pending'.
  3. Bank in whitelist with manual 'broken' is NOT auto-promoted.
  4. Bank not in whitelist with stale 'supported' is demoted to 'pending'.
  5. Running twice produces identical state (idempotence).
"""
from __future__ import annotations

import pytest

from app.models.bank import Bank
from app.services.bank_service import (
    SUPPORTED_BANK_CODES,
    BankService,
    _EXTRACTOR_NOTES,
)


@pytest.fixture
def banks_seeded(db):
    """Seed all whitelisted codes + a couple of non-whitelisted ones, all 'pending'."""
    rows = [
        Bank(name="Сбербанк", code="sber", is_popular=True),
        Bank(name="Т-Банк", code="tbank", is_popular=True),
        Bank(name="Озон Банк", code="ozon", is_popular=True),
        Bank(name="Яндекс Банк", code="yandex", is_popular=True),
        Bank(name="Альфа-Банк", code="alfa", is_popular=True),
        Bank(name="ВТБ", code="vtb", is_popular=True),
    ]
    db.add_all(rows)
    db.commit()
    return rows


def _by_code(db, code: str) -> Bank:
    return db.query(Bank).filter(Bank.code == code).one()


def test_fresh_state_promotes_whitelisted_banks(db, banks_seeded):
    counters = BankService(db).ensure_extractor_status_baseline()

    assert counters["promoted"] == 4
    assert counters["demoted"] == 0
    for code in SUPPORTED_BANK_CODES:
        bank = _by_code(db, code)
        assert bank.extractor_status == "supported"
        assert bank.extractor_notes == _EXTRACTOR_NOTES[code]


def test_non_whitelisted_bank_stays_pending(db, banks_seeded):
    BankService(db).ensure_extractor_status_baseline()

    alfa = _by_code(db, "alfa")
    vtb = _by_code(db, "vtb")
    assert alfa.extractor_status == "pending"
    assert alfa.extractor_notes is None
    assert vtb.extractor_status == "pending"


def test_manual_broken_status_is_preserved(db, banks_seeded):
    sber = _by_code(db, "sber")
    sber.extractor_status = "broken"
    sber.extractor_notes = "regressed after format change 2026-04-01"
    db.commit()

    counters = BankService(db).ensure_extractor_status_baseline()

    sber = _by_code(db, "sber")
    assert sber.extractor_status == "broken"
    assert sber.extractor_notes == "regressed after format change 2026-04-01"
    assert counters["untouched_manual"] >= 1


def test_manual_in_review_status_is_preserved(db, banks_seeded):
    alfa = _by_code(db, "alfa")
    alfa.extractor_status = "in_review"
    db.commit()

    BankService(db).ensure_extractor_status_baseline()

    alfa = _by_code(db, "alfa")
    assert alfa.extractor_status == "in_review"


def test_stale_supported_demoted_when_removed_from_whitelist(db, banks_seeded):
    # Simulate: vtb was once supported, but extractor regressed and code was
    # dropped from SUPPORTED_BANK_CODES. Symmetric demote should fire.
    vtb = _by_code(db, "vtb")
    vtb.extractor_status = "supported"
    vtb.extractor_notes = "PDF (vtb_pdf_v1) — pretend it once worked"
    db.commit()

    counters = BankService(db).ensure_extractor_status_baseline()

    vtb = _by_code(db, "vtb")
    assert vtb.extractor_status == "pending"
    assert vtb.extractor_notes is None
    assert counters["demoted"] >= 1


def test_idempotence_two_runs_identical_state(db, banks_seeded):
    svc = BankService(db)
    svc.ensure_extractor_status_baseline()
    snapshot_first = {
        b.code: (b.extractor_status, b.extractor_notes)
        for b in db.query(Bank).all()
    }

    counters_second = svc.ensure_extractor_status_baseline()

    snapshot_second = {
        b.code: (b.extractor_status, b.extractor_notes)
        for b in db.query(Bank).all()
    }
    assert snapshot_first == snapshot_second
    assert counters_second["promoted"] == 0
    assert counters_second["demoted"] == 0
