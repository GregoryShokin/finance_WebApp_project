"""Pytest fixtures for FinanceApp unit tests.

Uses SQLite in-memory so no Docker/PostgreSQL is required.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
# Import all models so SQLAlchemy can resolve relationships before create_all
import app.models.user  # noqa: F401
import app.models.account  # noqa: F401
import app.models.category  # noqa: F401
import app.models.transaction  # noqa: F401
import app.models.budget  # noqa: F401
import app.models.budget_alert  # noqa: F401
import app.models.goal  # noqa: F401
import app.models.counterparty  # noqa: F401
import app.models.import_session  # noqa: F401
import app.models.import_row  # noqa: F401
import app.models.transaction_category_rule  # noqa: F401
import app.models.fingerprint_alias  # noqa: F401
import app.models.counterparty_fingerprint  # noqa: F401
try:
    import app.models.real_asset  # noqa: F401
    import app.models.installment_purchase  # noqa: F401
    import app.models.capital_snapshot  # noqa: F401
except Exception:
    pass


@pytest.fixture(scope="function")
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # SQLite doesn't support all PostgreSQL features, but is sufficient for logic tests.
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def user(db):
    from app.models.user import User
    u = User(email="test@example.com", password_hash="x", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def bank(db):
    """Test bank used as `bank_id` for any account created in tests.

    bank_id is NOT NULL (migration 0055), so every account fixture must
    reference a real bank row. Reusing a single placeholder bank keeps
    fixtures decoupled from real bank data.
    """
    from app.models.bank import Bank
    b = Bank(name="Test Bank", code="test_bank", is_popular=False)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@pytest.fixture
def regular_account(db, user, bank):
    from app.models.account import Account
    acc = Account(
        user_id=user.id,
        bank_id=bank.id,
        name="Основной",
        account_type="main",
        balance=Decimal("100000"),
        currency="RUB",
        is_active=True,
        is_credit=False,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def credit_account(db, user, bank):
    from app.models.account import Account
    acc = Account(
        user_id=user.id,
        bank_id=bank.id,
        name="Кредит",
        account_type="loan",
        balance=Decimal("-200000"),
        credit_current_amount=Decimal("200000"),
        monthly_payment=Decimal("15000"),
        currency="RUB",
        is_active=True,
        is_credit=True,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def interest_category(db, user):
    from app.models.category import Category
    cat = Category(
        user_id=user.id,
        name="Проценты по кредитам",
        kind="expense",
        priority="expense_essential",
        regularity="regular",
        is_system=True,
        icon_name="percent",
        color="#94a3b8",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def make_transaction(db, **kwargs):
    from app.models.transaction import Transaction
    tx = Transaction(**kwargs)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx
