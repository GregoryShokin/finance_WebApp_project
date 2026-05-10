"""Integration tests for `POST /imports/queue/confirm-all-filled` (v1.24).

Tests verify that `ImportService.confirm_all_filled` correctly stamps
user_confirmed_at on filled+valid rows while leaving incomplete rows
untouched — enforcing §5.4 (no blind bulk-ack) and §12.1 (no orphan
transfers).
"""
from __future__ import annotations

from decimal import Decimal

from app.models.account import Account
from app.models.bank import Bank
from app.models.category import Category
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_service import ImportService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_bank(db, *, code: str) -> Bank:
    b = Bank(name=code.title(), code=code, is_popular=False)
    db.add(b); db.commit(); db.refresh(b)
    return b


def _mk_account(db, *, user_id: int, bank: Bank, name: str) -> Account:
    a = Account(
        user_id=user_id, bank_id=bank.id, name=name,
        currency="RUB", balance=Decimal("0"),
    )
    db.add(a); db.commit(); db.refresh(a)
    return a


def _mk_category(db, *, user_id: int, name: str = "Продукты") -> Category:
    c = Category(
        user_id=user_id, name=name, kind="expense",
        priority="expense_essential", regularity="monthly",
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


def _mk_session(
    db,
    *,
    user_id: int,
    account_id: int | None,
    status: str = "preview_ready",
    filename: str = "t.csv",
) -> ImportSession:
    s = ImportSession(
        user_id=user_id, filename=filename, source_type="csv",
        status=status, account_id=account_id, file_content="",
        detected_columns=[], parse_settings={}, mapping_json={}, summary_json={},
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def _mk_row(
    db,
    *,
    session_id: int,
    row_index: int,
    status: str = "warning",
    normalized: dict,
) -> ImportRow:
    r = ImportRow(
        session_id=session_id,
        row_index=row_index,
        raw_data_json={"date": "2026-01-15", "amount": normalized.get("amount", "100.00")},
        normalized_data_json=normalized,
        status=status,
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def _base_normalized(account_id: int, category_id: int) -> dict:
    """Minimal valid normalized_data for a regular expense row."""
    return {
        "amount": "500.00",
        "type": "expense",
        "direction": "expense",
        "operation_type": "regular",
        "account_id": account_id,
        "category_id": category_id,
        "description": "Оплата товаров",
        "transaction_date": "2026-01-15T12:00:00+00:00",
        "skeleton": "оплата товаров",
        "fingerprint": f"fp{account_id:08d}{category_id:08d}",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_confirm_all_filled_stamps_all_valid_warning_rows(db, user):
    """3 filled warning-rows → all confirmed, status flipped to ready."""
    bank = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=bank, name="Карта")
    cat = _mk_category(db, user_id=user.id)
    session = _mk_session(db, user_id=user.id, account_id=acc.id)

    rows = [
        _mk_row(db, session_id=session.id, row_index=i, status="warning",
                normalized=_base_normalized(acc.id, cat.id))
        for i in range(1, 4)
    ]

    result = ImportService(db).confirm_all_filled(user_id=user.id)

    assert result["confirmed_count"] == 3
    assert result["skipped_count"] == 0
    assert result["skipped_row_ids"] == []

    for row in rows:
        db.refresh(row)
        assert row.status == "ready"
        nd = row.normalized_data_json or {}
        assert nd.get("user_confirmed_at") is not None


# ---------------------------------------------------------------------------
# Mixed: some filled, some not
# ---------------------------------------------------------------------------


def test_confirm_all_filled_mixed_rows_skips_incomplete(db, user):
    """2 filled rows + 2 without category → 2 confirmed, 2 in skipped_row_ids."""
    bank = _mk_bank(db, code="tbank")
    acc = _mk_account(db, user_id=user.id, bank=bank, name="Дебет")
    cat = _mk_category(db, user_id=user.id)
    session = _mk_session(db, user_id=user.id, account_id=acc.id)

    # Rows 1–2: valid (have category_id).
    valid_rows = [
        _mk_row(db, session_id=session.id, row_index=i, status="warning",
                normalized=_base_normalized(acc.id, cat.id))
        for i in range(1, 3)
    ]
    # Rows 3–4: invalid (no category_id — required for regular op).
    invalid_nd = {
        **_base_normalized(acc.id, cat.id),
        "category_id": None,
    }
    invalid_rows = [
        _mk_row(db, session_id=session.id, row_index=i, status="warning",
                normalized=invalid_nd)
        for i in range(3, 5)
    ]

    result = ImportService(db).confirm_all_filled(user_id=user.id)

    assert result["confirmed_count"] == 2
    assert result["skipped_count"] == 2
    assert set(result["skipped_row_ids"]) == {invalid_rows[0].id, invalid_rows[1].id}

    for row in valid_rows:
        db.refresh(row)
        assert row.status == "ready"
        assert row.normalized_data_json.get("user_confirmed_at") is not None

    for row in invalid_rows:
        db.refresh(row)
        assert row.status == "warning"  # unchanged
        assert not row.normalized_data_json.get("user_confirmed_at")


# ---------------------------------------------------------------------------
# Transfer without target_account_id
# ---------------------------------------------------------------------------


def test_confirm_all_filled_skips_transfer_without_target(db, user):
    """Transfer row missing target_account_id is NOT confirmed (§12.1)."""
    bank = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=bank, name="Основная")
    session = _mk_session(db, user_id=user.id, account_id=acc.id)

    # Transfer with source but no target.
    row = _mk_row(
        db, session_id=session.id, row_index=1, status="warning",
        normalized={
            "amount": "1000.00",
            "type": "expense",
            "direction": "expense",
            "operation_type": "transfer",
            "account_id": acc.id,
            "target_account_id": None,
            "description": "Перевод между счетами",
            "transaction_date": "2026-01-15T12:00:00+00:00",
            "skeleton": "перевод между счетами",
            "fingerprint": "fp_transfer_no_target",
        },
    )

    result = ImportService(db).confirm_all_filled(user_id=user.id)

    assert result["confirmed_count"] == 0
    assert row.id in result["skipped_row_ids"]

    db.refresh(row)
    assert row.status == "warning"
    assert not (row.normalized_data_json or {}).get("user_confirmed_at")


# ---------------------------------------------------------------------------
# Credit-split without amounts
# ---------------------------------------------------------------------------


def test_confirm_all_filled_skips_credit_split_without_amounts(db, user):
    """Credit-split row without principal/interest amounts is NOT confirmed."""
    bank = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=bank, name="Текущий")
    credit_acc = _mk_account(db, user_id=user.id, bank=bank, name="Кредитный")
    session = _mk_session(db, user_id=user.id, account_id=acc.id)

    row = _mk_row(
        db, session_id=session.id, row_index=1, status="warning",
        normalized={
            "amount": "5000.00",
            "type": "expense",
            "direction": "expense",
            "operation_type": "transfer",
            "requires_credit_split": True,
            "account_id": acc.id,
            "credit_account_id": credit_acc.id,
            "target_account_id": credit_acc.id,
            "credit_principal_amount": None,   # missing — must block confirm
            "credit_interest_amount": None,
            "description": "Платёж по кредиту",
            "transaction_date": "2026-01-15T12:00:00+00:00",
            "skeleton": "платёж по кредиту",
            "fingerprint": "fp_credit_split_no_amounts",
        },
    )

    result = ImportService(db).confirm_all_filled(user_id=user.id)

    assert result["confirmed_count"] == 0
    assert row.id in result["skipped_row_ids"]

    db.refresh(row)
    assert not (row.normalized_data_json or {}).get("user_confirmed_at")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_confirm_all_filled_is_idempotent(db, user):
    """Second call returns 0 confirmed (all already stamped)."""
    bank = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=bank, name="Карта")
    cat = _mk_category(db, user_id=user.id)
    session = _mk_session(db, user_id=user.id, account_id=acc.id)

    _mk_row(db, session_id=session.id, row_index=1, status="warning",
            normalized=_base_normalized(acc.id, cat.id))

    svc = ImportService(db)
    first = svc.confirm_all_filled(user_id=user.id)
    assert first["confirmed_count"] == 1

    second = svc.confirm_all_filled(user_id=user.id)
    assert second["confirmed_count"] == 0
    assert second["skipped_count"] == 0  # already-confirmed rows are silent


# ---------------------------------------------------------------------------
# Cross-session
# ---------------------------------------------------------------------------


def test_confirm_all_filled_processes_rows_from_multiple_sessions(db, user):
    """Rows from two different preview_ready sessions are both confirmed."""
    bank = _mk_bank(db, code="tbank")
    acc1 = _mk_account(db, user_id=user.id, bank=bank, name="Счёт 1")
    acc2 = _mk_account(db, user_id=user.id, bank=bank, name="Счёт 2")
    cat = _mk_category(db, user_id=user.id)

    s1 = _mk_session(db, user_id=user.id, account_id=acc1.id, filename="s1.csv")
    s2 = _mk_session(db, user_id=user.id, account_id=acc2.id, filename="s2.csv")

    row1 = _mk_row(db, session_id=s1.id, row_index=1, status="warning",
                   normalized=_base_normalized(acc1.id, cat.id))
    row2 = _mk_row(db, session_id=s2.id, row_index=1, status="warning",
                   normalized=_base_normalized(acc2.id, cat.id))

    result = ImportService(db).confirm_all_filled(user_id=user.id)

    assert result["confirmed_count"] == 2
    assert result["skipped_count"] == 0

    for row in (row1, row2):
        db.refresh(row)
        assert row.status == "ready"
        assert (row.normalized_data_json or {}).get("user_confirmed_at") is not None


# ---------------------------------------------------------------------------
# Eligibility filter: ineligible sessions are skipped
# ---------------------------------------------------------------------------


def test_confirm_all_filled_ignores_non_preview_ready_sessions(db, user):
    """Sessions that aren't preview_ready or have no account_id are excluded."""
    bank = _mk_bank(db, code="sber")
    acc = _mk_account(db, user_id=user.id, bank=bank, name="Карта")
    cat = _mk_category(db, user_id=user.id)

    queued = _mk_session(db, user_id=user.id, account_id=acc.id, status="queued")
    no_acc = _mk_session(db, user_id=user.id, account_id=None, filename="orphan.csv")

    row_q = _mk_row(db, session_id=queued.id, row_index=1, status="warning",
                    normalized=_base_normalized(acc.id, cat.id))
    row_n = _mk_row(db, session_id=no_acc.id, row_index=1, status="warning",
                    normalized=_base_normalized(acc.id, cat.id))

    result = ImportService(db).confirm_all_filled(user_id=user.id)

    assert result["confirmed_count"] == 0  # nothing eligible

    for row in (row_q, row_n):
        db.refresh(row)
        assert not (row.normalized_data_json or {}).get("user_confirmed_at")


# ---------------------------------------------------------------------------
# Cross-user isolation
# ---------------------------------------------------------------------------


def test_confirm_all_filled_does_not_touch_other_users_rows(db, user):
    """confirm_all_filled(user_id=A) must not stamp rows belonging to user B."""
    from app.models.user import User

    other = User(email="other2@example.com", password_hash="x", is_active=True)
    db.add(other); db.commit(); db.refresh(other)

    bank = _mk_bank(db, code="sber")
    user_acc = _mk_account(db, user_id=user.id, bank=bank, name="Мой счёт")
    other_acc = _mk_account(db, user_id=other.id, bank=bank, name="Чужой счёт")
    cat = _mk_category(db, user_id=other.id)

    other_session = _mk_session(db, user_id=other.id, account_id=other_acc.id)
    other_row = _mk_row(db, session_id=other_session.id, row_index=1, status="warning",
                        normalized=_base_normalized(other_acc.id, cat.id))

    # Calling user has no eligible sessions.
    _mk_session(db, user_id=user.id, account_id=user_acc.id)

    ImportService(db).confirm_all_filled(user_id=user.id)

    db.refresh(other_row)
    assert not (other_row.normalized_data_json or {}).get("user_confirmed_at")
