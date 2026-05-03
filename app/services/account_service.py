from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session
from app.models.account import Account
from app.models.transaction import Transaction as TransactionModel
from app.repositories.account_repository import AccountRepository
from app.repositories.bank_repository import BankRepository


class AccountNotFoundError(Exception):
    pass


class BankRequiredError(ValueError):
    """Raised when an account create/update is missing or has an invalid bank_id."""


class CloseAccountValidationError(ValueError):
    """Raised when close()/reopen() validation fails (spec §13, v1.20)."""


class AccountService:
    def __init__(self, db: Session):
        self.repo = AccountRepository(db)
        self.bank_repo = BankRepository(db)

    def _require_bank(self, bank_id: int | None) -> int:
        if bank_id is None:
            raise BankRequiredError("Укажи банк счёта — без него выписки не распознаются.")
        bank = self.bank_repo.get_by_id(int(bank_id))
        if bank is None:
            raise BankRequiredError("Указанный банк не найден.")
        return bank.id

    @staticmethod
    def _normalize_credit_payload(payload: dict) -> dict:
        data = dict(payload)

        account_type = data.get("account_type")
        if account_type is None:
            # Legacy fallback: is_credit=True maps to 'loan'.
            account_type = "loan" if bool(data.get("is_credit")) else "main"
        data["account_type"] = account_type
        data["is_credit"] = account_type == "loan"

        _no_deposit = {
            "deposit_interest_rate": None,
            "deposit_open_date": None,
            "deposit_close_date": None,
            "deposit_capitalization_period": None,
        }
        _no_credit = {
            "credit_current_amount": None,
            "credit_interest_rate": None,
            "credit_term_remaining": None,
            "credit_limit_original": None,
            "monthly_payment": None,
        }

        if account_type == "loan":
            current_amount = data.get("credit_current_amount") or data.get("credit_current_balance")
            if current_amount is not None:
                current_amount = Decimal(str(current_amount))
                data["credit_current_amount"] = current_amount
                data["balance"] = -current_amount
            data.update(_no_deposit)
        elif account_type == "credit_card":
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data.update({"credit_current_amount": None, "credit_interest_rate": None, "credit_term_remaining": None})
            data.update(_no_deposit)
        elif account_type == "installment_card":
            data["is_credit"] = False
            data["balance"] = Decimal("0")
            data["credit_term_remaining"] = None
            data.update(_no_deposit)
        elif account_type == "savings":
            data["is_credit"] = False
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data.update(_no_credit)
        elif account_type == "savings_account":
            # Накопительный счёт: бессрочный, только ставка — без дат и капитализации
            data["is_credit"] = False
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data.update(_no_credit)
            data["deposit_open_date"] = None
            data["deposit_close_date"] = None
            data["deposit_capitalization_period"] = None
        else:
            # main, cash, marketplace, broker, currency — no credit or deposit params
            data["is_credit"] = False
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data.update(_no_credit)
            data.update(_no_deposit)

        return data

    def _resolve_bank_id(self, bank_id: int | None, account_type: str | None) -> int:
        if account_type == "cash":
            if bank_id:
                return bank_id
            unknown = self.bank_repo.get_by_code("unknown")
            if unknown is None:
                raise BankRequiredError("Банк-заглушка 'unknown' не найден в базе. Обратитесь к администратору.")
            return unknown.id
        return self._require_bank(bank_id)

    def create(self, **kwargs) -> Account:
        kwargs["bank_id"] = self._resolve_bank_id(kwargs.get("bank_id"), kwargs.get("account_type"))
        return self.repo.create(**self._normalize_credit_payload(kwargs))

    def list(self, *, user_id: int, include_closed: bool = False) -> list[Account]:
        return self.repo.list_by_user(user_id, include_closed=include_closed)

    def list_with_last_transaction(
        self, *, user_id: int, include_closed: bool = False,
    ) -> list[Account]:
        return self.repo.list_by_user_with_last_transaction(
            user_id, include_closed=include_closed,
        )

    def get(self, *, account_id: int, user_id: int) -> Account:
        account = self.repo.get_by_id_and_user(account_id, user_id)
        if not account:
            raise AccountNotFoundError("Account not found")
        return account

    def update(self, *, account_id: int, user_id: int, **kwargs) -> Account:
        account = self.get(account_id=account_id, user_id=user_id)
        effective_type = kwargs.get("account_type") or account.account_type
        if "bank_id" in kwargs or effective_type == "cash":
            kwargs["bank_id"] = self._resolve_bank_id(kwargs.get("bank_id"), effective_type)
        # Spec §13 — closure validation when caller updates is_closed/closed_at
        # via the generic update path (not the dedicated close() endpoint).
        if "is_closed" in kwargs or "closed_at" in kwargs:
            self._validate_closure_payload(account, kwargs)
        return self.repo.update(account, **self._normalize_credit_payload(kwargs))

    def _validate_closure_payload(self, account: Account, kwargs: dict) -> None:
        is_closed = kwargs.get("is_closed", account.is_closed)
        closed_at = kwargs.get("closed_at", account.closed_at)
        if is_closed:
            if closed_at is None:
                raise CloseAccountValidationError(
                    "Укажи дату закрытия счёта."
                )
            self._validate_closed_at_value(account, closed_at)
            # Closing an account also flips is_active to False atomically.
            kwargs.setdefault("is_active", False)
        else:
            # Reopening: clear closed_at unless caller explicitly preserved it
            kwargs["closed_at"] = None

    def _validate_closed_at_value(self, account: Account, closed_at: date) -> None:
        today = datetime.now(timezone.utc).date()
        if closed_at > today:
            raise CloseAccountValidationError(
                "Дата закрытия не может быть в будущем."
            )
        last_tx_date = self.repo.get_max_transaction_date(account.id)
        if last_tx_date is not None:
            last_date = last_tx_date.date() if isinstance(last_tx_date, datetime) else last_tx_date
            if closed_at < last_date:
                raise CloseAccountValidationError(
                    f"Дата закрытия не может быть раньше последней транзакции "
                    f"({last_date.isoformat()})."
                )

    def close(self, *, account_id: int, user_id: int, closed_at: date) -> Account:
        """Mark account as closed (spec §13, v1.20)."""
        account = self.get(account_id=account_id, user_id=user_id)
        if account.is_closed:
            raise CloseAccountValidationError("Счёт уже закрыт.")
        self._validate_closed_at_value(account, closed_at)
        return self.repo.update(
            account,
            is_closed=True,
            closed_at=closed_at,
            is_active=False,
        )

    def reopen(self, *, account_id: int, user_id: int) -> Account:
        """Reopen a previously closed account (spec §13, v1.20)."""
        account = self.get(account_id=account_id, user_id=user_id)
        if not account.is_closed:
            raise CloseAccountValidationError("Счёт не был закрыт.")
        return self.repo.update(
            account,
            is_closed=False,
            closed_at=None,
            is_active=True,
        )

    def delete(self, *, account_id: int, user_id: int) -> None:
        self.repo.delete(self.get(account_id=account_id, user_id=user_id))

    def adjust_balance(
        self,
        *,
        account_id: int,
        user_id: int,
        target_balance: Decimal,
        comment: str | None = None,
    ) -> TransactionModel:
        account = self.get(account_id=account_id, user_id=user_id)
        delta = target_balance - account.balance
        if delta == 0:
            raise ValueError("Баланс уже равен указанному значению.")

        tx_type = "income" if delta > 0 else "expense"
        amount = abs(delta)
        description = comment or f"Корректировка баланса: {float(account.balance):+.2f} → {float(target_balance):+.2f}"

        tx = TransactionModel(
            user_id=user_id,
            account_id=account.id,
            amount=amount,
            currency=account.currency,
            type=tx_type,
            operation_type="adjustment",
            description=description,
            transaction_date=datetime.now(timezone.utc),
            affects_analytics=False,
        )
        self.repo.db.add(tx)
        account.balance = target_balance
        self.repo.db.add(account)
        self.repo.db.commit()
        self.repo.db.refresh(tx)
        return tx
