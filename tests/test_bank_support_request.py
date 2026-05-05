"""Tests for BankSupportRequestRepository (Этап 1.4 MVP launch)."""
from __future__ import annotations

import pytest

from app.models.bank import Bank
from app.repositories.bank_support_request_repository import BankSupportRequestRepository


@pytest.fixture
def alfa_bank(db):
    bank = Bank(name="Альфа-Банк", code="alfa", is_popular=True, extractor_status="pending")
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


def test_create_persists_request(db, user, alfa_bank):
    repo = BankSupportRequestRepository(db)
    req = repo.create(
        user_id=user.id,
        bank_name="Альфа-Банк",
        bank_id=alfa_bank.id,
        note="есть PDF и XLSX",
    )
    assert req.id is not None
    assert req.user_id == user.id
    assert req.bank_id == alfa_bank.id
    assert req.bank_name == "Альфа-Банк"
    assert req.note == "есть PDF и XLSX"
    assert req.status == "pending"
    assert req.resolved_at is None


def test_create_strips_whitespace_and_drops_empty_note(db, user):
    repo = BankSupportRequestRepository(db)
    req = repo.create(user_id=user.id, bank_name="  Точка  ", bank_id=None, note="   ")
    assert req.bank_name == "Точка"
    assert req.bank_id is None
    assert req.note is None


def test_list_for_user_orders_by_created_desc(db, user, alfa_bank):
    repo = BankSupportRequestRepository(db)
    first = repo.create(user_id=user.id, bank_name="Альфа", bank_id=alfa_bank.id)
    second = repo.create(user_id=user.id, bank_name="Точка")

    result = repo.list_for_user(user.id)
    assert [r.id for r in result] == [second.id, first.id]


def test_find_open_matches_pending_by_bank_id(db, user, alfa_bank):
    repo = BankSupportRequestRepository(db)
    created = repo.create(user_id=user.id, bank_name="Альфа", bank_id=alfa_bank.id)

    found = repo.find_open_for_user_and_bank(
        user_id=user.id, bank_id=alfa_bank.id, bank_name="Альфа",
    )
    assert found is not None
    assert found.id == created.id


def test_find_open_ignores_resolved_requests(db, user, alfa_bank):
    repo = BankSupportRequestRepository(db)
    created = repo.create(user_id=user.id, bank_name="Альфа", bank_id=alfa_bank.id)
    created.status = "added"
    db.commit()

    found = repo.find_open_for_user_and_bank(
        user_id=user.id, bank_id=alfa_bank.id, bank_name="Альфа",
    )
    assert found is None


def test_find_open_falls_back_to_bank_name_when_no_id(db, user):
    repo = BankSupportRequestRepository(db)
    # ASCII name — SQLite ILIKE is locale-insensitive only on ASCII; on
    # Postgres in prod it folds Cyrillic too.
    created = repo.create(user_id=user.id, bank_name="Tochka")

    # Different casing — ILIKE still matches.
    found = repo.find_open_for_user_and_bank(
        user_id=user.id, bank_id=None, bank_name="tochka",
    )
    assert found is not None
    assert found.id == created.id


def test_freetext_dedup_uses_name_match(db, user):
    """Юзер дважды нажимает «Запросить» для freetext банка → один record.

    Имитирует поведение API-handler'а: find_open_for_user_and_bank → если
    есть открытый запрос, возвращаем его, иначе создаём новый.
    """
    repo = BankSupportRequestRepository(db)
    bank_name = "Regional Bank Y"

    existing_first = repo.find_open_for_user_and_bank(
        user_id=user.id, bank_id=None, bank_name=bank_name,
    )
    assert existing_first is None
    created = repo.create(user_id=user.id, bank_name=bank_name)

    # second click — handler must reuse, not duplicate
    existing_second = repo.find_open_for_user_and_bank(
        user_id=user.id, bank_id=None, bank_name=bank_name,
    )
    assert existing_second is not None
    assert existing_second.id == created.id

    # double-check: only one row in DB for this user
    rows = repo.list_for_user(user.id)
    assert len([r for r in rows if r.bank_name == bank_name]) == 1
