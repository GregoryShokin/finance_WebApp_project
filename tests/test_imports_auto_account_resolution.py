"""Auto-account-recognition Шаг 2 — Level-3 fallback in ImportService.upload_file.

Pattern mirrors test_imports_unsupported_bank.py — drive `upload_source` end-
to-end through the real recognizer + SQLite session, with a stub CSV
extractor that injects extraction.meta values (bank_code, account_type_hint,
contract_number, statement_account_number).

Invariants pinned by these tests:

  • Level 1 (contract) wins over Level 3 (bank+type) when both could match.
  • Level 3 fires only when contract / statement_account didn't match AND the
    extractor recognised the bank (bank_code != 'unknown').
  • Exactly 1 candidate at (bank, type) → suggested_account_id is set with
    confidence 0.7 (lower than Level 1/2's 0.93–0.99 because the match is
    profile-based, not identifier-unique).
  • 2+ candidates → no auto-pick; account_candidates list returned for UI.
  • 0 candidates → requires_account_creation=True + suggested_bank_id set.
  • bank_code='unknown' → Level 3 skipped entirely (no random profile-match).
  • account_type_hint=None → Level 3 returns ALL bank accounts (broader pool).
  • Closed accounts are never auto-attached (spec §13).
  • bank_code + account_type_hint always populated in the response payload
    (Шаг 1 contract).
"""
from __future__ import annotations

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.services.import_service import ImportService


CSV_BODY = (
    b"date,amount,description\n"
    b"2026-01-01,100.00,Coffee\n"
    b"2026-01-02,50.00,Tea\n"
)


@pytest.fixture
def import_service(db):
    """Real ImportService with a stub CSV extractor that injects all four
    auto-recognition meta keys (bank_code, account_type_hint, contract,
    statement_account). Tests override per-meta values via the injectors."""
    service = ImportService(db)
    real_extractor = service.extractors.get("csv")

    class _ConfigurableCSVExtractor:
        # Stored on the instance, mutated by helpers below.
        bank_code: str | None = None
        account_type_hint: str | None = None
        contract_number: str | None = None
        statement_account_number: str | None = None

        def extract(self, *, filename, raw_bytes, options=None):
            result = real_extractor.extract(filename=filename, raw_bytes=raw_bytes, options=options)
            if self.bank_code is not None:
                result.meta["bank_code"] = self.bank_code
            if self.account_type_hint is not None:
                result.meta["account_type_hint"] = self.account_type_hint
            if self.contract_number is not None:
                result.meta["contract_number"] = self.contract_number
                result.meta["contract_match_reason"] = "test-contract-reason"
                result.meta["contract_match_confidence"] = 0.99
            if self.statement_account_number is not None:
                result.meta["statement_account_number"] = self.statement_account_number
                result.meta["statement_account_match_reason"] = "test-statement-reason"
                result.meta["statement_account_match_confidence"] = 0.97
            return result

    extractor = _ConfigurableCSVExtractor()
    service.extractors._extractors["csv"] = extractor
    # Expose the configurable extractor so tests can set its fields.
    service._test_extractor = extractor
    return service


def _configure(service: ImportService, **kwargs) -> None:
    for k, v in kwargs.items():
        setattr(service._test_extractor, k, v)


def _make_bank(db, *, code: str, name: str, status: str = "supported") -> Bank:
    bank = Bank(name=name, code=code, is_popular=True, extractor_status=status)
    db.add(bank)
    db.commit()
    db.refresh(bank)
    return bank


def _make_account(
    db,
    *,
    user_id: int,
    bank_id: int,
    name: str = "Test account",
    account_type: str = "main",
    contract: str | None = None,
    statement_account: str | None = None,
    is_active: bool = True,
    is_closed: bool = False,
) -> Account:
    account = Account(
        user_id=user_id,
        bank_id=bank_id,
        name=name,
        account_type=account_type,
        currency="RUB",
        contract_number=contract,
        statement_account_number=statement_account,
        is_active=is_active,
        is_closed=is_closed,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _upload(service: ImportService, *, user_id: int) -> dict:
    return service.upload_source(
        user_id=user_id,
        filename="statement.csv",
        raw_bytes=CSV_BODY,
        delimiter=",",
        force_new=False,
    )


# ─── Level 3: exact-1 match → auto-attach ──────────────────────────────────


def test_level3_unique_match_attaches_with_lower_confidence(import_service, user, db):
    bank = _make_bank(db, code="sber", name="Сбербанк")
    account = _make_account(db, user_id=user.id, bank_id=bank.id, account_type="credit_card")

    _configure(import_service, bank_code="sber", account_type_hint="credit_card")
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] == account.id
    # 0.7 — profile-based match. Strictly below Level 1/2 (0.93–0.99) so the UI
    # can render different visual treatments per confidence tier.
    assert response["suggested_account_match_confidence"] == pytest.approx(0.7)
    assert response["suggested_account_match_reason"]
    assert "Сбербанк" in response["suggested_account_match_reason"]
    # Level 3 also exposes bank_id even though it auto-attached — frontend
    # uses it for "create another account at this bank" deep-link.
    assert response["suggested_bank_id"] == bank.id
    assert response["account_candidates"] == []
    assert response["requires_account_creation"] is False


# ─── Level 3: multiple candidates → no auto-pick, return list ──────────────


def test_level3_multiple_candidates_returns_list(import_service, user, db):
    bank = _make_bank(db, code="sber", name="Сбербанк")
    a1 = _make_account(db, user_id=user.id, bank_id=bank.id, name="Дебет 1", account_type="main")
    a2 = _make_account(db, user_id=user.id, bank_id=bank.id, name="Дебет 2", account_type="main")

    _configure(import_service, bank_code="sber", account_type_hint="main")
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] is None
    assert response["suggested_account_match_reason"] is None
    assert response["suggested_account_match_confidence"] is None
    assert response["suggested_bank_id"] == bank.id
    assert response["requires_account_creation"] is False

    candidate_ids = {c["id"] for c in response["account_candidates"]}
    assert candidate_ids == {a1.id, a2.id}
    # Each candidate carries enough fields for the picker to render.
    for c in response["account_candidates"]:
        assert c["bank_id"] == bank.id
        assert c["bank_name"] == "Сбербанк"
        assert c["account_type"] == "main"
        assert c["is_closed"] is False


# ─── Level 3: zero candidates → propose account creation ───────────────────


def test_level3_no_match_proposes_account_creation(import_service, user, db):
    bank = _make_bank(db, code="sber", name="Сбербанк")
    # User has NO Sber account at all.

    _configure(import_service, bank_code="sber", account_type_hint="credit_card")
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] is None
    assert response["account_candidates"] == []
    assert response["suggested_bank_id"] == bank.id
    assert response["account_type_hint"] == "credit_card"
    assert response["requires_account_creation"] is True


# ─── Level 3 skipped for unknown bank ──────────────────────────────────────


def test_level3_skipped_for_unknown_bank_code(import_service, user, db):
    """When extractor returned bank_code='unknown', Level 3 must NOT fire —
    matching by account_type alone across all the user's banks would mismatch
    e.g. a Tinkoff debit card with an unrelated CSV."""
    bank = _make_bank(db, code="sber", name="Сбербанк")
    _make_account(db, user_id=user.id, bank_id=bank.id, account_type="main")

    _configure(import_service, bank_code="unknown", account_type_hint="main")
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] is None
    assert response["suggested_bank_id"] is None
    assert response["account_candidates"] == []
    assert response["requires_account_creation"] is False


def test_level3_skipped_for_missing_bank_code(import_service, user, db):
    """`bank_code` absent / None — same effect as 'unknown'."""
    _make_bank(db, code="sber", name="Сбербанк")
    _configure(import_service, bank_code=None, account_type_hint="main")
    response = _upload(import_service, user_id=user.id)
    assert response["suggested_account_id"] is None
    assert response["account_candidates"] == []


# ─── Level 1 wins over Level 3 ─────────────────────────────────────────────


def test_level1_contract_match_wins_over_level3(import_service, user, db):
    """Two Sber accounts: one matches by contract, the other by bank+type. The
    contract winner must be picked, and account_candidates must NOT be filled
    in (Level 3 didn't run because Level 1 already resolved)."""
    bank = _make_bank(db, code="sber", name="Сбербанк")
    contract_match = _make_account(
        db, user_id=user.id, bank_id=bank.id,
        name="Sber Credit by contract", account_type="credit_card",
        contract="EXACT-CONTRACT-001",
    )
    _make_account(
        db, user_id=user.id, bank_id=bank.id,
        name="Sber Credit no contract", account_type="credit_card",
    )

    _configure(
        import_service,
        bank_code="sber",
        account_type_hint="credit_card",
        contract_number="EXACT-CONTRACT-001",
    )
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] == contract_match.id
    assert response["suggested_account_match_reason"] == "test-contract-reason"
    assert response["suggested_account_match_confidence"] == pytest.approx(0.99)
    assert response["account_candidates"] == []  # Level 3 didn't run


def test_level2_statement_account_match_wins_over_level3(import_service, user, db):
    bank = _make_bank(db, code="sber", name="Сбербанк")
    statement_match = _make_account(
        db, user_id=user.id, bank_id=bank.id,
        name="Sber Debit by statement_account", account_type="main",
        statement_account="40817810700006095914",
    )
    _make_account(
        db, user_id=user.id, bank_id=bank.id,
        name="Sber Debit no statement_account", account_type="main",
    )

    _configure(
        import_service,
        bank_code="sber",
        account_type_hint="main",
        statement_account_number="40817810700006095914",
    )
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] == statement_match.id
    assert response["suggested_account_match_reason"] == "test-statement-reason"
    assert response["suggested_account_match_confidence"] == pytest.approx(0.97)


# ─── Level 3 type filter ───────────────────────────────────────────────────


def test_level3_filters_by_account_type(import_service, user, db):
    """User has both a credit and a debit Sber account. With type_hint=
    'credit_card', only the credit one is a candidate."""
    bank = _make_bank(db, code="sber", name="Сбербанк")
    credit = _make_account(
        db, user_id=user.id, bank_id=bank.id,
        name="Sber Credit", account_type="credit_card",
    )
    _make_account(
        db, user_id=user.id, bank_id=bank.id,
        name="Sber Debit", account_type="main",
    )

    _configure(import_service, bank_code="sber", account_type_hint="credit_card")
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] == credit.id


def test_level3_no_type_hint_returns_all_bank_accounts(import_service, user, db):
    """When the extractor couldn't disambiguate the type (account_type_hint=None),
    Level 3 returns every account at the bank as a candidate. With 2+ accounts
    of different types, that means the picker."""
    bank = _make_bank(db, code="tbank", name="Т-Банк")
    a1 = _make_account(db, user_id=user.id, bank_id=bank.id, account_type="credit_card")
    a2 = _make_account(db, user_id=user.id, bank_id=bank.id, account_type="main")

    _configure(import_service, bank_code="tbank", account_type_hint=None)
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] is None
    candidate_ids = {c["id"] for c in response["account_candidates"]}
    assert candidate_ids == {a1.id, a2.id}


# ─── Closed accounts excluded ──────────────────────────────────────────────


def test_level3_excludes_closed_accounts(import_service, user, db):
    """Spec §13 — closed accounts must NOT be auto-attached on a fresh upload.
    Even if the user closed all their Sber accounts, the upload should fall
    through to requires_account_creation=True."""
    bank = _make_bank(db, code="sber", name="Сбербанк")
    _make_account(
        db, user_id=user.id, bank_id=bank.id,
        account_type="main", is_closed=True, is_active=False,
    )

    _configure(import_service, bank_code="sber", account_type_hint="main")
    response = _upload(import_service, user_id=user.id)

    assert response["suggested_account_id"] is None
    assert response["account_candidates"] == []
    assert response["requires_account_creation"] is True


# ─── Шаг 1 contract: response always carries bank_code + account_type_hint ──


def test_response_always_carries_bank_and_type_keys(import_service, user, db):
    """Even for sessions with no detected account match, the new Шаг 1 keys
    are present in the response with safe defaults — frontend can `obj.bank_code`
    without optional-chaining."""
    response = _upload(import_service, user_id=user.id)
    assert "bank_code" in response
    assert "account_type_hint" in response
    assert "suggested_account_match_reason" in response
    assert "suggested_account_match_confidence" in response
    assert "suggested_bank_id" in response
    assert "account_candidates" in response
    assert "requires_account_creation" in response
    assert response["account_candidates"] == []
    assert response["requires_account_creation"] is False


def test_level3_unsupported_bank_match_triggers_guard(import_service, user, db):
    """Existing Шаг 1.6 guard — if Level 3 auto-attaches to an account whose
    bank's extractor isn't supported, BankUnsupportedError still fires.
    Symmetric with Level 1/2 behaviour: any matched account on an unsupported
    bank is rejected, regardless of which level matched."""
    from app.services.import_service import BankUnsupportedError

    bank = _make_bank(db, code="alfa", name="Альфа-Банк", status="pending")
    _make_account(db, user_id=user.id, bank_id=bank.id, account_type="main")

    _configure(import_service, bank_code="alfa", account_type_hint="main")
    with pytest.raises(BankUnsupportedError) as exc_info:
        _upload(import_service, user_id=user.id)
    assert exc_info.value.bank_id == bank.id
    assert exc_info.value.extractor_status == "pending"
