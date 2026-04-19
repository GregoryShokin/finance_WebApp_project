"""Test: credit_disbursement must NOT appear in income aggregation.

GAP #8 — Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §3.5
Decision 2026-04-19.

Fixture: user with salary 100k (income/regular) + credit disbursement 500k.
Expected: income = 100k, NOT 600k. FI-score not improved by disbursement.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest


TODAY = datetime(2026, 4, 1)
PREV_MONTH = datetime(2026, 3, 1)


def _make_salary(db, user_id: int, account_id: int, amount: Decimal = Decimal("100000")):
    from app.models.transaction import Transaction
    tx = Transaction(
        user_id=user_id,
        account_id=account_id,
        amount=amount,
        currency="RUB",
        type="income",
        operation_type="regular",
        is_regular=True,
        affects_analytics=True,
        transaction_date=PREV_MONTH,
    )
    db.add(tx)
    db.commit()
    return tx


def _make_disbursement(db, user_id: int, account_id: int, credit_account_id: int, amount: Decimal = Decimal("500000")):
    from app.models.transaction import Transaction
    tx = Transaction(
        user_id=user_id,
        account_id=account_id,
        credit_account_id=credit_account_id,
        amount=amount,
        currency="RUB",
        type="income",
        operation_type="credit_disbursement",
        is_regular=False,
        affects_analytics=False,  # NON_ANALYTICS set by service at creation
        transaction_date=PREV_MONTH,
    )
    db.add(tx)
    db.commit()
    return tx


def test_credit_disbursement_excluded_from_metrics_income(db, user, regular_account, credit_account):
    """Salary 100k + disbursement 500k → metrics reports income = 100k."""
    _make_salary(db, user.id, regular_account.id)
    _make_disbursement(db, user.id, regular_account.id, credit_account.id)

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)

    # Calculate for previous month (March 2026)
    result = svc.calculate_flow(user.id, 2026, 3)

    # Regular income should be 100k, NOT 600k
    # basic_flow = regular_income - regular_expense = 100k - 0 = 100k
    assert result["basic_flow"] == Decimal("100000.00"), (
        f"Expected basic_flow=100000, got {result['basic_flow']}. "
        "credit_disbursement is leaking into income."
    )


def test_dti_not_affected_by_disbursement(db, user, regular_account, credit_account):
    """DTI denominator (income) must not include credit_disbursement."""
    _make_salary(db, user.id, regular_account.id)
    _make_disbursement(db, user.id, regular_account.id, credit_account.id)

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    result = svc.calculate_dti(user.id)

    # regular_income used for DTI denominator should be 100k
    assert result["regular_income"] == Decimal("100000.00"), (
        f"DTI denominator inflated by credit_disbursement: {result['regular_income']}"
    )


def test_credit_disbursement_affects_analytics_false(db, user, regular_account, credit_account):
    """credit_disbursement should have affects_analytics=False when created via service."""
    from app.services.transaction_service import NON_ANALYTICS_OPERATION_TYPES
    assert "credit_disbursement" in NON_ANALYTICS_OPERATION_TYPES, (
        "credit_disbursement must be in NON_ANALYTICS_OPERATION_TYPES to ensure "
        "affects_analytics=False is set automatically."
    )


def test_credit_payment_removed_from_enum():
    """credit_payment must NOT exist in TransactionOperationType enum."""
    from app.models.transaction import TransactionOperationType
    op_types = {e.value for e in TransactionOperationType}
    assert "credit_payment" not in op_types, (
        "credit_payment still in TransactionOperationType enum after migration."
    )
    assert "credit_interest" not in op_types, (
        "credit_interest still in TransactionOperationType enum after migration."
    )


def test_credit_payment_removed_from_schema_enum():
    """credit_payment must NOT exist in schema TransactionOperationType enum."""
    from app.schemas.transaction import TransactionOperationType
    op_types = {e.value for e in TransactionOperationType}
    assert "credit_payment" not in op_types
    assert "credit_interest" not in op_types


def test_interest_category_is_system_and_cannot_be_deleted(db, user, interest_category):
    """System category 'Проценты по кредитам' cannot be deleted via CategoryService."""
    from app.services.category_service import CategoryService, CategoryValidationError

    svc = CategoryService(db)
    with pytest.raises(CategoryValidationError, match="нельзя удалять"):
        svc.delete_category(user_id=user.id, category_id=interest_category.id)


def test_interest_category_is_system_and_cannot_be_updated(db, user, interest_category):
    """System category 'Проценты по кредитам' cannot be renamed via CategoryService."""
    from app.services.category_service import CategoryService, CategoryValidationError

    svc = CategoryService(db)
    with pytest.raises(CategoryValidationError, match="нельзя изменять"):
        svc.update_category(
            user_id=user.id,
            category_id=interest_category.id,
            updates={"name": "Хочу переименовать"},
        )


def test_ensure_system_categories_creates_interest_category(db, user):
    """ensure_default_categories must create 'Проценты по кредитам' system category."""
    from app.services.category_service import CategoryService
    from app.models.category import Category

    svc = CategoryService(db)
    svc.ensure_default_categories(user_id=user.id)

    cats = (
        db.query(Category)
        .filter(
            Category.user_id == user.id,
            Category.is_system.is_(True),
            Category.name == "Проценты по кредитам",
        )
        .all()
    )
    assert len(cats) == 1, f"Expected 1 system category, got {len(cats)}"
    cat = cats[0]
    assert cat.regularity == "regular"
    assert cat.kind == "expense"
    assert cat.priority == "expense_essential"
