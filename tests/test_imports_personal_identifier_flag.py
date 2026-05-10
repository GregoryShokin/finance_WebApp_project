"""Tests for the `is_personal_identifier` flag on preview-row payloads.

Spec: Brand Registry §17 / Пайплайн импорта v1.26.

Backend exposes the same predicate (`is_personal_identifier_row`) it uses
internally to skip Brand auto-bind, so the moderator UI can hide brand controls
(BrandPrompt + «Выбрать бренд») on rows whose only counterparty signal is a
phone / contract / person name.

The flag is a pure projection of `normalized_data` — adding it to the
serializer must not change any other behavior.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_service import ImportService


def _mk_bank(db, *, code: str) -> Bank:
    b = Bank(name=code.title(), code=code, is_popular=False)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _mk_account(db, *, user_id: int, bank: Bank) -> Account:
    a = Account(
        user_id=user_id,
        bank_id=bank.id,
        name=f"{bank.code}-acc",
        currency="RUB",
        balance=Decimal("0"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_session(db, *, user_id: int, account_id: int) -> ImportSession:
    s = ImportSession(
        user_id=user_id,
        filename="t.csv",
        source_type="csv",
        status="preview_ready",
        account_id=account_id,
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _mk_row(
    db,
    *,
    session_id: int,
    skeleton: str,
    tokens: dict | None,
) -> ImportRow:
    nd: dict = {
        "amount": "100.00",
        "direction": "expense",
        "transaction_date": "2026-04-01T12:00:00+00:00",
        "skeleton": skeleton,
        "fingerprint": f"fp{session_id:08d}",
    }
    if tokens is not None:
        nd["tokens"] = tokens
    r = ImportRow(
        session_id=session_id,
        row_index=1,
        raw_data_json={"date": "2026-04-01"},
        normalized_data_json=nd,
        status="ready",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _serialize_one(db, row) -> dict:
    return ImportService(db)._serialize_preview_row(row)


# ──────────────────────────────────────────────────────────────────────
# Personal-identifier rows → flag = True
# ──────────────────────────────────────────────────────────────────────


def test_phone_only_row_marked_personal_identifier(db, user):
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db,
        session_id=s.id,
        skeleton="внешний перевод <PHONE>",
        tokens={"phone": "+79161234567"},
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is True


def test_contract_only_row_marked_personal_identifier(db, user):
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db,
        session_id=s.id,
        skeleton="внутрибанковский перевод <CONTRACT>",
        tokens={"contract": "5267981263"},
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is True


def test_person_name_present_row_marked_personal_identifier(db, user):
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db,
        session_id=s.id,
        skeleton="перевод <PERSON>",
        tokens={"person_name_present": True},
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is True


# ──────────────────────────────────────────────────────────────────────
# Merchant rows / empty tokens → flag = False
# ──────────────────────────────────────────────────────────────────────


def test_merchant_org_row_not_personal_identifier(db, user):
    """ООО / ПАО etc. is a legal merchant signal — Brand controls remain."""
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db,
        session_id=s.id,
        skeleton="оплата <ORG>",
        tokens={"counterparty_org": 'ООО "Пятёрочка"'},
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is False


def test_phone_with_org_row_not_personal_identifier(db, user):
    """Org signal overrides phone — this is a merchant who happens to leak
    a phone in their description (e.g. courier service)."""
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db,
        session_id=s.id,
        skeleton="оплата <ORG> <PHONE>",
        tokens={
            "phone": "+79161234567",
            "counterparty_org": 'ООО "Курьер"',
        },
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is False


def test_sbp_merchant_row_not_personal_identifier(db, user):
    """SBP merchant ID is a real merchant signal — kept as brand-bearing."""
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db,
        session_id=s.id,
        skeleton="26033 <SBP_PAYMENT>",
        tokens={"sbp_merchant_id": "26033"},
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is False


def test_row_without_tokens_not_personal_identifier(db, user):
    """Plain merchant skeleton without any extracted token (e.g.
    'оплата pyaterochka') stays brand-eligible."""
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = _mk_row(
        db, session_id=s.id, skeleton="оплата pyaterochka", tokens=None,
    )

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is False


def test_legacy_row_without_skeleton_safe_default(db, user):
    """Rows without a skeleton (legacy / failed-normalization) default to False
    — the predicate is undefined without a skeleton, but the UI must not crash."""
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    row = ImportRow(
        session_id=s.id,
        row_index=1,
        raw_data_json={},
        normalized_data_json={"amount": "1.00"},  # no skeleton
        status="error",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    payload = _serialize_one(db, row)

    assert payload["is_personal_identifier"] is False


# ──────────────────────────────────────────────────────────────────────
# Queue endpoint integration — flag survives queue serialization
# ──────────────────────────────────────────────────────────────────────


def test_queue_preview_includes_personal_identifier_flag(db, user):
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank)
    s = _mk_session(db, user_id=user.id, account_id=acc.id)
    _mk_row(
        db,
        session_id=s.id,
        skeleton="внешний перевод <PHONE>",
        tokens={"phone": "+79161234567"},
    )

    payload = ImportService(db).get_queue_preview(user_id=user.id)

    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["is_personal_identifier"] is True
