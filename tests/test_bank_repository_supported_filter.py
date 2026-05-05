"""Filter-tests for BankRepository.list_all / search supported_only flag (Этап 1)."""
from __future__ import annotations

import pytest

from app.models.bank import Bank
from app.repositories.bank_repository import BankRepository


@pytest.fixture
def banks_mixed(db):
    # Names use ASCII so SQLite ILIKE (Cyrillic-insensitive only on Postgres)
    # doesn't muddy the filter assertion.
    rows = [
        Bank(name="Sber Bank", code="sber", is_popular=True, extractor_status="supported"),
        Bank(name="TBank", code="tbank", is_popular=True, extractor_status="supported"),
        Bank(name="Alfa Bank", code="alfa", is_popular=True, extractor_status="pending"),
        Bank(name="VTB", code="vtb", is_popular=True, extractor_status="in_review"),
        Bank(name="Home Bank", code="home_credit", is_popular=False, extractor_status="broken"),
    ]
    db.add_all(rows)
    db.commit()
    return rows


def test_list_all_default_returns_every_bank(db, banks_mixed):
    result = BankRepository(db).list_all()
    assert len(result) == 5


def test_list_all_supported_only_filters(db, banks_mixed):
    result = BankRepository(db).list_all(supported_only=True)
    codes = {b.code for b in result}
    assert codes == {"sber", "tbank"}


def test_search_supported_only_excludes_pending_match(db, banks_mixed):
    # 'bank' matches Sber Bank, TBank, Alfa Bank, Home Bank — VTB has no
    # 'bank' substring; the filter must prune in_review/pending/broken.
    all_match = BankRepository(db).search("bank")
    assert {b.code for b in all_match} == {"sber", "tbank", "alfa", "home_credit"}
    supported_match = BankRepository(db).search("bank", supported_only=True)
    codes = {b.code for b in supported_match}
    assert codes == {"sber", "tbank"}


def test_search_returns_empty_when_no_supported_match(db, banks_mixed):
    result = BankRepository(db).search("Home", supported_only=True)
    assert result == []
