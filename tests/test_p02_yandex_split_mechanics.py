"""Regression tests for P-02 (Яндекс Сплит/Дебет mechanics).

Problem statement:
  - Яндекс Дебет sends N rows to Сплит for loan repayment.
  - Яндекс Сплит receives 1 or more income rows (principal + interest).
  - Old code: no matching possible → all rows left unclassified.

Fix:
  1. bank_mechanics suggests auto_exclude for Сплит income «погашение основного долга»
     (covered by phantom from Дебет transfer pair).
  2. bank_mechanics classifies Сплит income «погашение процентов» as regular expense
     «Проценты по кредитам».
  3. bank_mechanics resolves target_account_id for Дебет transfer rows by contract.

Scenarios tested:
  1. suggest_exclude fires for Сплит income «погашение основного долга»
  2. suggest_exclude does NOT fire for Дебет expense «погашение» (wrong direction/account)
  3. Interest income on Сплит → operation_type='regular', category='Проценты по кредитам'
  4. Дебет expense «погашение по договору №X» → suggest_target_by_contract + resolves account
  5. Confidence boost is meaningful (≥0.12) for the new rules
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.bank_mechanics_service import BankMechanicsService, BankMechanicsResult


def _make_account(account_type: str, is_credit: bool = False, account_id: int = 1):
    acc = MagicMock()
    acc.id = account_id
    acc.account_type = account_type
    acc.is_credit = is_credit
    return acc


def _make_session(user_id: int = 1, session_id: int = 1):
    s = MagicMock()
    s.id = session_id
    s.user_id = user_id
    return s


# ---------------------------------------------------------------------------
# 1. suggest_exclude for Сплит income «погашение основного долга»
# ---------------------------------------------------------------------------

def test_split_income_principal_suggests_exclude(db):
    """Яндекс Сплит (loan) income «погашение основного долга» → suggest_exclude=True."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение основного долга договор <CONTRACT>",
        direction="income",
        bank_code="yandex",
        # Migration 0054: legacy "credit" → "loan".
        account=_make_account("loan", is_credit=True),
        session=_make_session(),
        total_amount=Decimal("17500"),
    )
    assert result.suggest_exclude is True, (
        f"expected suggest_exclude=True for Сплит income principal, got: {result}"
    )
    assert result.confidence_boost >= 0.15


# ---------------------------------------------------------------------------
# 2. suggest_exclude does NOT fire for Дебет expense
# ---------------------------------------------------------------------------

def test_debit_expense_principal_no_exclude(db):
    """Яндекс Дебет (main) expense «погашение» → suggest_exclude=False (it's a transfer)."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение договор <CONTRACT>",
        direction="expense",
        bank_code="yandex",
        # Migration 0054: legacy "regular" → "main".
        account=_make_account("main"),
        session=_make_session(),
        total_amount=Decimal("18000"),
    )
    assert result.suggest_exclude is False
    assert result.operation_type == "transfer"


# ---------------------------------------------------------------------------
# 3. Interest income on Сплит → regular expense «Проценты по кредитам»
# ---------------------------------------------------------------------------

def test_split_income_interest_is_expense(db):
    """Яндекс Сплит income «погашение процентов» → operation_type='regular',
    category_name='Проценты по кредитам', suggest_exclude=False."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение процентов договор <CONTRACT>",
        direction="income",
        bank_code="yandex",
        account=_make_account("installment_card", is_credit=True),
        session=_make_session(),
        total_amount=Decimal("200.61"),
    )
    assert result.suggest_exclude is False
    assert result.operation_type == "regular"
    assert result.category_name == "Проценты по кредитам"
    assert result.confidence_boost >= 0.15


# ---------------------------------------------------------------------------
# 4. Дебет transfer → resolves target_account_id by contract
# ---------------------------------------------------------------------------

def test_debit_transfer_resolves_target_by_contract(db, regular_account):
    """Яндекс Дебет expense «погашение по договору №X» → resolved_target_account_id
    set when an account with contract_number=X exists for the user."""
    from app.models.account import Account

    split_acc = Account(
        user_id=regular_account.user_id,
        bank_id=regular_account.bank_id,
        name="Яндекс Сплит",
        account_type="installment_card",
        balance=Decimal("-50000"),
        currency="RUB",
        is_active=True,
        is_credit=True,
        contract_number="КС20251126483806054311",
    )
    db.add(split_acc)
    db.commit()
    db.refresh(split_acc)

    svc = BankMechanicsService(db)
    session = _make_session(user_id=regular_account.user_id)

    result = svc.apply(
        skeleton="погашение договор <CONTRACT>",
        direction="expense",
        bank_code="yandex",
        account=_make_account("main", account_id=regular_account.id),
        session=session,
        total_amount=Decimal("200.61"),
        identifier_key="contract",
        identifier_value="КС20251126483806054311",
    )

    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id == split_acc.id, (
        f"expected target={split_acc.id}, got {result.resolved_target_account_id}"
    )


# ---------------------------------------------------------------------------
# 5. No resolution when contract not found
# ---------------------------------------------------------------------------

def test_debit_transfer_no_resolution_unknown_contract(db, regular_account):
    """Unknown contract → resolved_target_account_id=None, operation stays transfer."""
    svc = BankMechanicsService(db)
    session = _make_session(user_id=regular_account.user_id)

    result = svc.apply(
        skeleton="погашение договор <CONTRACT>",
        direction="expense",
        bank_code="yandex",
        account=_make_account("main", account_id=regular_account.id),
        session=session,
        total_amount=Decimal("18000"),
        identifier_key="contract",
        identifier_value="NONEXISTENT123",
    )

    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id is None
    assert result.suggest_exclude is False
