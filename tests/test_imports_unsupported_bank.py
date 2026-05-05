"""Bank-supported guard tests for Этап 1 Шаг 1.6.

Pattern mirrors `test_imports_duplicate_upload.py` — drive `ImportService.upload_source`
through the real extractor + recognizer + SQLite session. We don't go through the
HTTP route; the route's contract is verified separately (it just maps the exception
to a 415 JSON response with `code='bank_unsupported'`).

Invariants pinned by these tests:

  * Account match → bank lookup → guard fires when extractor_status != 'supported'.
  * No account match (no contract on file, brand-new bank) → guard does NOT fire.
    The user assigns an account in queue; frontend disclaimer catches intent
    BEFORE upload click.
  * `in_review` and `broken` are treated identically to `pending` — the guard
    is binary (`supported` vs everything else). Frontend tone (which copy to
    show) is its concern, backend just blocks.
  * Sessions for unsupported banks are NEVER created — verified by counting
    `ImportSession` rows after a rejected upload.
"""
from __future__ import annotations

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_session import ImportSession
from app.services.import_service import (
    BankUnsupportedError,
    ImportService,
)


# CSV-with-contract — the recognition layer extracts contract_number from the
# CSV body via a separate detector path, but for SQLite-only tests we shortcut:
# create the Account with `contract_number` set, then the upload flow finds it
# via `find_by_contract_number(parsed_contract)`. The contract appears on
# the CSV header line below as a fake column the recognizer ignores, but
# `extraction.meta["contract_number"]` is what the matcher reads — so we
# override the extractor at the meta level via the `_inject_contract` helper
# in the fixture.
CSV_BODY_WITH_CONTRACT = (
    b"date,amount,description\n"
    b"2026-01-01,100.00,Coffee\n"
    b"2026-01-02,50.00,Tea\n"
)
CONTRACT_NUMBER = "TEST-CONTRACT-1234"


@pytest.fixture
def import_service(db, monkeypatch):
    """Real ImportService with a stubbed extractor that injects a fixed
    contract_number into extraction.meta. Real recognition_service runs
    on the CSV body, but the CSV doesn't normally surface contract on its
    own — so we patch the CSV extractor to inject the contract that points
    the matcher at our test account."""
    service = ImportService(db)

    real_extractor = service.extractors.get("csv")

    class _ContractCSVExtractor:
        def extract(self, *, filename, raw_bytes, options=None):
            result = real_extractor.extract(filename=filename, raw_bytes=raw_bytes, options=options)
            # Mutate meta so find_by_contract_number can match our test account.
            result.meta["contract_number"] = CONTRACT_NUMBER
            return result

    # Registry uses `_extractors` dict internally; swap the csv entry rather
    # than monkeypatching `.get` — keeps the get() return for `pdf`/`xlsx`
    # untouched in case a test grows.
    service.extractors._extractors["csv"] = _ContractCSVExtractor()
    return service


def _make_bank(db, *, code: str, name: str, status: str) -> Bank:
    bank = Bank(name=name, code=code, is_popular=True, extractor_status=status)
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


def _make_account(db, *, user_id: int, bank_id: int, contract: str) -> Account:
    account = Account(
        user_id=user_id,
        bank_id=bank_id,
        name=f"Test account {contract}",
        account_type="main",
        currency="RUB",
        contract_number=contract,
        is_active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _upload(service: ImportService, *, user_id: int) -> dict:
    return service.upload_source(
        user_id=user_id,
        filename="statement.csv",
        raw_bytes=CSV_BODY_WITH_CONTRACT,
        delimiter=",",
        force_new=False,
    )


# ─── guard fires on unsupported bank ────────────────────────────────────────


def test_upload_with_pending_bank_rejects(import_service, user, db):
    bank = _make_bank(db, code="alfa", name="Альфа-Банк", status="pending")
    _make_account(db, user_id=user.id, bank_id=bank.id, contract=CONTRACT_NUMBER)

    with pytest.raises(BankUnsupportedError) as exc_info:
        _upload(import_service, user_id=user.id)

    err = exc_info.value
    assert err.bank_id == bank.id
    assert err.bank_name == "Альфа-Банк"
    assert err.extractor_status == "pending"
    # No session created — DB stays clean for unsupported banks.
    assert db.query(ImportSession).filter(ImportSession.user_id == user.id).count() == 0


def test_upload_with_in_review_bank_rejects(import_service, user, db):
    """`in_review` is a manual status (parser in active development) — guard
    treats it the same as `pending`. Only `supported` passes."""
    bank = _make_bank(db, code="vtb", name="ВТБ", status="in_review")
    _make_account(db, user_id=user.id, bank_id=bank.id, contract=CONTRACT_NUMBER)

    with pytest.raises(BankUnsupportedError) as exc_info:
        _upload(import_service, user_id=user.id)
    assert exc_info.value.extractor_status == "in_review"


def test_upload_with_broken_bank_rejects(import_service, user, db):
    """`broken` = extractor regressed after format change. Same gate."""
    bank = _make_bank(db, code="hc", name="Home Credit", status="broken")
    _make_account(db, user_id=user.id, bank_id=bank.id, contract=CONTRACT_NUMBER)

    with pytest.raises(BankUnsupportedError) as exc_info:
        _upload(import_service, user_id=user.id)
    assert exc_info.value.extractor_status == "broken"


# ─── guard passes on supported bank ─────────────────────────────────────────


def test_upload_with_supported_bank_passes(import_service, user, db):
    bank = _make_bank(db, code="sber", name="Сбербанк", status="supported")
    _make_account(db, user_id=user.id, bank_id=bank.id, contract=CONTRACT_NUMBER)

    response = _upload(import_service, user_id=user.id)
    assert response["session_id"] is not None
    assert response["suggested_account_id"] is not None
    # Session for supported bank IS created.
    assert db.query(ImportSession).filter(ImportSession.user_id == user.id).count() == 1


# ─── guard does not fire when no account matched ────────────────────────────


def test_upload_without_matching_account_passes(import_service, user, db):
    """User has an unsupported-bank account but the contract on file does NOT
    match. Guard cannot identify the bank, so it doesn't fire — session is
    created with `suggested_account_id=None`. Frontend disclaimer is the
    proactive line of defense for this flow."""
    bank = _make_bank(db, code="alfa", name="Альфа-Банк", status="pending")
    # Account exists, but its contract differs from the one on the statement.
    _make_account(db, user_id=user.id, bank_id=bank.id, contract="OTHER-CONTRACT-9999")

    response = _upload(import_service, user_id=user.id)
    assert response["session_id"] is not None
    assert response["suggested_account_id"] is None
    # Session is created — guard fires only on positive bank match.
    assert db.query(ImportSession).filter(ImportSession.user_id == user.id).count() == 1


def test_upload_with_no_accounts_at_all_passes(import_service, user, db):
    """Brand-new user, no accounts. The matcher returns None, guard doesn't
    fire. User will create an account afterwards via the queue UI."""
    response = _upload(import_service, user_id=user.id)
    assert response["session_id"] is not None
    assert response["suggested_account_id"] is None


# ─── payload contract pin ───────────────────────────────────────────────────


def test_unsupported_error_carries_all_route_fields(import_service, user, db):
    """Exception carries (bank_id, bank_name, extractor_status). The route
    handler reads these via attribute access to build the JSON payload —
    contract pin so a refactor doesn't accidentally drop one of the three."""
    bank = _make_bank(db, code="raif", name="Райффайзенбанк", status="pending")
    _make_account(db, user_id=user.id, bank_id=bank.id, contract=CONTRACT_NUMBER)

    with pytest.raises(BankUnsupportedError) as exc_info:
        _upload(import_service, user_id=user.id)

    err = exc_info.value
    assert hasattr(err, "bank_id")
    assert hasattr(err, "bank_name")
    assert hasattr(err, "extractor_status")
    assert isinstance(err.bank_id, int)
    assert isinstance(err.bank_name, str) and err.bank_name
    assert err.extractor_status in {"pending", "in_review", "broken"}
