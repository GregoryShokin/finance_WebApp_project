"""Tests for closed-account state (spec §13, v1.20).

Covers:
  • close() / reopen() service methods + validations.
  • repository.list_by_user with include_closed flag.
  • Validation errors: future date, before-last-tx, missing closed_at.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.models.transaction import Transaction
from app.models.user import User
from app.services.account_service import (
    AccountService,
    CloseAccountValidationError,
)


@pytest.fixture
def svc(db):
    return AccountService(db)


@pytest.fixture
def closed_candidate(db, user, bank):
    """A regular debit account candidate for closure tests."""
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Тинькоф (закрывающийся)",
        account_type="main", balance=Decimal("0"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


class TestCloseAccount:
    def test_close_account_sets_is_closed_and_closed_at(
        self, db, user, closed_candidate, svc,
    ):
        when = date(2026, 4, 1)
        result = svc.close(
            account_id=closed_candidate.id, user_id=user.id, closed_at=when,
        )
        assert result.is_closed is True
        assert result.closed_at == when

    def test_close_account_validates_closed_at_not_in_future(
        self, db, user, closed_candidate, svc,
    ):
        future = date.today() + timedelta(days=1)
        with pytest.raises(CloseAccountValidationError, match="не может быть в будущем"):
            svc.close(
                account_id=closed_candidate.id, user_id=user.id, closed_at=future,
            )

    def test_close_account_validates_closed_at_after_last_transaction(
        self, db, user, closed_candidate, svc,
    ):
        last_tx = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
        tx = Transaction(
            user_id=user.id, account_id=closed_candidate.id,
            amount=Decimal("100"), currency="RUB", type="expense",
            operation_type="regular", description="late tx",
            transaction_date=last_tx,
        )
        db.add(tx); db.commit()

        with pytest.raises(CloseAccountValidationError, match="последней транзакции"):
            svc.close(
                account_id=closed_candidate.id,
                user_id=user.id,
                closed_at=date(2026, 4, 10),  # earlier than last_tx
            )

    def test_close_account_sets_is_active_false(
        self, db, user, closed_candidate, svc,
    ):
        result = svc.close(
            account_id=closed_candidate.id,
            user_id=user.id,
            closed_at=date(2026, 4, 1),
        )
        assert result.is_active is False

    def test_close_account_rejects_already_closed(
        self, db, user, closed_candidate, svc,
    ):
        svc.close(
            account_id=closed_candidate.id, user_id=user.id, closed_at=date(2026, 4, 1),
        )
        with pytest.raises(CloseAccountValidationError, match="уже закрыт"):
            svc.close(
                account_id=closed_candidate.id, user_id=user.id, closed_at=date(2026, 4, 1),
            )


# ---------------------------------------------------------------------------
# reopen()
# ---------------------------------------------------------------------------


class TestReopenAccount:
    def test_reopen_clears_closed_state(
        self, db, user, closed_candidate, svc,
    ):
        svc.close(
            account_id=closed_candidate.id, user_id=user.id, closed_at=date(2026, 4, 1),
        )
        result = svc.reopen(
            account_id=closed_candidate.id, user_id=user.id,
        )
        assert result.is_closed is False
        assert result.closed_at is None
        assert result.is_active is True

    def test_reopen_rejects_account_that_was_not_closed(
        self, db, user, closed_candidate, svc,
    ):
        with pytest.raises(CloseAccountValidationError, match="не был закрыт"):
            svc.reopen(account_id=closed_candidate.id, user_id=user.id)


# ---------------------------------------------------------------------------
# list with include_closed
# ---------------------------------------------------------------------------


class TestListWithClosedFilter:
    def test_get_accounts_default_excludes_closed(
        self, db, user, bank, svc,
    ):
        active = Account(
            user_id=user.id, bank_id=bank.id, name="Активный",
            account_type="main", balance=Decimal("0"),
            currency="RUB", is_active=True, is_credit=False,
        )
        closed = Account(
            user_id=user.id, bank_id=bank.id, name="Закрытый",
            account_type="main", balance=Decimal("0"),
            currency="RUB", is_active=False, is_credit=False,
            is_closed=True, closed_at=date(2026, 1, 1),
        )
        db.add(active); db.add(closed); db.commit()

        rows = svc.list(user_id=user.id)
        names = {r.name for r in rows}
        assert "Активный" in names
        assert "Закрытый" not in names

    def test_get_accounts_include_closed_returns_all(
        self, db, user, bank, svc,
    ):
        active = Account(
            user_id=user.id, bank_id=bank.id, name="Активный",
            account_type="main", balance=Decimal("0"),
            currency="RUB", is_active=True, is_credit=False,
        )
        closed = Account(
            user_id=user.id, bank_id=bank.id, name="Закрытый",
            account_type="main", balance=Decimal("0"),
            currency="RUB", is_active=False, is_credit=False,
            is_closed=True, closed_at=date(2026, 1, 1),
        )
        db.add(active); db.add(closed); db.commit()

        rows = svc.list(user_id=user.id, include_closed=True)
        names = {r.name for r in rows}
        assert {"Активный", "Закрытый"}.issubset(names)
