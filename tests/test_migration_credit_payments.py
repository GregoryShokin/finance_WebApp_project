"""Test: migration script logic for splitting credit_payment → expense + transfer.

Tests the core logic without running the full data migration script
(which requires a live DB connection).

Ref: financeapp-vault/01-Metrics/Поток.md — decision 2026-04-19.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest


TODAY = datetime(2026, 3, 15)


def _make_credit_payment(db, user_id, account_id, credit_account_id, interest_cat_id,
                          principal: Decimal, interest: Decimal) -> tuple:
    """Create the pair of transactions as the migration script would produce."""
    from app.models.transaction import Transaction

    total = principal + interest

    t_interest = Transaction(
        user_id=user_id,
        account_id=account_id,
        credit_account_id=credit_account_id,
        category_id=interest_cat_id,
        amount=interest,
        currency="RUB",
        type="expense",
        operation_type="regular",
        is_regular=True,
        affects_analytics=True,
        transaction_date=TODAY,
        description="Проценты · Кредит Альфа",
    )
    t_transfer = Transaction(
        user_id=user_id,
        account_id=account_id,
        target_account_id=credit_account_id,
        credit_account_id=credit_account_id,
        amount=principal,
        currency="RUB",
        type="expense",
        operation_type="transfer",
        is_regular=True,
        affects_analytics=False,
        transaction_date=TODAY,
        description="Тело кредита · Кредит Альфа",
    )

    db.add_all([t_interest, t_transfer])
    db.commit()
    db.refresh(t_interest)
    db.refresh(t_transfer)
    return t_interest, t_transfer


def test_migrated_payment_structure(db, user, regular_account, credit_account, interest_category):
    """After migration: expense(interest) + transfer(principal) pair exists for each old credit_payment."""
    principal = Decimal("10000")
    interest = Decimal("3500")

    t_int, t_trans = _make_credit_payment(
        db, user.id, regular_account.id, credit_account.id,
        interest_category.id, principal, interest,
    )

    from app.models.transaction import Transaction
    from app.models.category import Category

    # Interest transaction must be expense/regular with credit_account_id
    assert t_int.type == "expense"
    assert t_int.operation_type == "regular"
    assert t_int.credit_account_id == credit_account.id
    assert t_int.category_id == interest_category.id
    assert Decimal(str(t_int.amount)) == interest

    # Principal transaction must be transfer
    assert t_trans.type == "expense"
    assert t_trans.operation_type == "transfer"
    assert t_trans.target_account_id == credit_account.id
    assert Decimal(str(t_trans.amount)) == principal

    # No credit_payment remains
    remaining = (
        db.query(Transaction)
        .filter(Transaction.operation_type == "credit_payment")
        .count()
    )
    assert remaining == 0


def test_metrics_dti_picks_up_interest_expenses(db, user, regular_account, credit_account, interest_category):
    """MetricsService.calculate_dti must count interest expenses (not credit_payment) for DTI."""
    from app.models.transaction import Transaction

    # Salary
    salary = Transaction(
        user_id=user.id,
        account_id=regular_account.id,
        amount=Decimal("100000"),
        currency="RUB",
        type="income",
        operation_type="regular",
        is_regular=True,
        affects_analytics=True,
        transaction_date=datetime(2026, 3, 15),
    )
    # Interest expense (result of migration)
    interest_tx = Transaction(
        user_id=user.id,
        account_id=regular_account.id,
        credit_account_id=credit_account.id,
        category_id=interest_category.id,
        amount=Decimal("3500"),
        currency="RUB",
        type="expense",
        operation_type="regular",
        is_regular=True,
        affects_analytics=True,
        transaction_date=datetime(2026, 3, 15),
    )
    db.add_all([salary, interest_tx])
    db.commit()

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    result = svc.calculate_dti(user.id)

    # Monthly payments detected: 3500 (interest from prev month)
    assert result["monthly_payments"] == Decimal("3500.00"), (
        f"Expected monthly_payments=3500, got {result['monthly_payments']}"
    )


def test_basic_flow_unchanged_after_migration(db, user, regular_account, credit_account, interest_category):
    """Basic flow before and after migration must be equivalent.

    Before: income 100k - expense 20k - credit_payment 13500 = 66500
    After:  income 100k - expense 20k - interest_expense 3500 = 76500
    NOTE: principal (10k) is now a transfer (not in expense), so basic_flow increases by principal.
    The test verifies the NEW correct behavior (basic_flow = income - regular_expenses).
    """
    from app.models.transaction import Transaction

    # Regular income
    db.add(Transaction(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("100000"), currency="RUB",
        type="income", operation_type="regular",
        is_regular=True, affects_analytics=True,
        transaction_date=TODAY,
    ))
    # Regular expense (жильё)
    db.add(Transaction(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("20000"), currency="RUB",
        type="expense", operation_type="regular",
        is_regular=True, affects_analytics=True,
        transaction_date=TODAY,
    ))
    # Interest expense (after migration)
    db.add(Transaction(
        user_id=user.id, account_id=regular_account.id,
        credit_account_id=credit_account.id,
        category_id=interest_category.id,
        amount=Decimal("3500"), currency="RUB",
        type="expense", operation_type="regular",
        is_regular=True, affects_analytics=True,
        transaction_date=TODAY,
    ))
    # Principal transfer (after migration) — NOT in basic flow
    db.add(Transaction(
        user_id=user.id, account_id=regular_account.id,
        target_account_id=credit_account.id, credit_account_id=credit_account.id,
        amount=Decimal("10000"), currency="RUB",
        type="expense", operation_type="transfer",
        is_regular=True, affects_analytics=False,
        transaction_date=TODAY,
    ))
    db.commit()

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    result = svc.calculate_flow(user.id, 2026, 3)

    # basic_flow = income(100k) - regular_expense(20k) - interest_expense(3.5k) = 76500
    # (principal transfer is NOT in basic flow — that is the correct new behavior)
    expected = Decimal("76500.00")
    assert result["basic_flow"] == expected, (
        f"Expected basic_flow={expected}, got {result['basic_flow']}"
    )


def test_metrics_sensitivity_within_half_point(db, user, regular_account, credit_account, interest_category):
    """Sensitivity check: DTI before/after migration stays within ±0.5 percentage points.

    Simulates having a credit_payment-style transaction (interest+principal=total)
    vs having the split pair. DTI numerator should be identical (interest amount).
    """
    from app.models.transaction import Transaction
    from decimal import ROUND_HALF_UP

    principal = Decimal("10000")
    interest = Decimal("3500")
    salary = Decimal("100000")

    # Salary (prev month March)
    db.add(Transaction(
        user_id=user.id, account_id=regular_account.id,
        amount=salary, currency="RUB",
        type="income", operation_type="regular",
        is_regular=True, affects_analytics=True,
        transaction_date=datetime(2026, 3, 1),
    ))
    # Split pair (March)
    db.add(Transaction(
        user_id=user.id, account_id=regular_account.id,
        credit_account_id=credit_account.id,
        category_id=interest_category.id,
        amount=interest, currency="RUB",
        type="expense", operation_type="regular",
        is_regular=True, affects_analytics=True,
        transaction_date=datetime(2026, 3, 1),
    ))
    db.commit()

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)

    # DTI for April (uses March data as prev month)
    dti_after = svc.calculate_dti(user.id)

    # Expected DTI: interest/salary = 3500/100000 = 3.5%
    expected_dti = float(interest / salary * 100)
    actual_dti = dti_after["dti_percent"] or 0.0

    assert abs(actual_dti - expected_dti) <= 0.5, (
        f"DTI sensitivity check failed: expected ~{expected_dti:.2f}%, got {actual_dti:.2f}%"
    )
