from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session
from app.models.account import Account
from app.models.transaction import Transaction as TransactionModel
from app.repositories.account_repository import AccountRepository


class AccountNotFoundError(Exception):
    pass


class AccountService:
    def __init__(self, db: Session):
        self.repo = AccountRepository(db)

    @staticmethod
    def _normalize_credit_payload(payload: dict) -> dict:
        data = dict(payload)

        account_type = data.get("account_type")
        if account_type is None:
            account_type = "credit" if bool(data.get("is_credit")) else "regular"
        data["account_type"] = account_type
        data["is_credit"] = account_type == "credit"

        if account_type == "credit":
            current_amount = data.get("credit_current_amount")
            if current_amount is None:
                current_amount = data.get("credit_current_balance")
            if current_amount is not None:
                current_amount = Decimal(str(current_amount))
                data["credit_current_amount"] = current_amount
                data["balance"] = -current_amount
            data["deposit_interest_rate"] = None
            data["deposit_open_date"] = None
            data["deposit_close_date"] = None
            data["deposit_capitalization_period"] = None
        elif account_type == "credit_card":
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data["credit_current_amount"] = None
            data["credit_interest_rate"] = None
            data["credit_term_remaining"] = None
            data["deposit_interest_rate"] = None
            data["deposit_open_date"] = None
            data["deposit_close_date"] = None
            data["deposit_capitalization_period"] = None
        elif account_type == "installment_card":
            data["is_credit"] = False
            data["balance"] = Decimal("0")
            data["credit_term_remaining"] = None
            data["deposit_interest_rate"] = None
            data["deposit_open_date"] = None
            data["deposit_close_date"] = None
            data["deposit_capitalization_period"] = None
        elif account_type == "deposit":
            data["is_credit"] = False
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data["credit_current_amount"] = None
            data["credit_interest_rate"] = None
            data["credit_term_remaining"] = None
            data["credit_limit_original"] = None
            data["monthly_payment"] = None
        else:
            data["credit_current_amount"] = None
            data["credit_interest_rate"] = None
            data["credit_term_remaining"] = None
            data["credit_limit_original"] = None
            data["monthly_payment"] = None
            data["deposit_interest_rate"] = None
            data["deposit_open_date"] = None
            data["deposit_close_date"] = None
            data["deposit_capitalization_period"] = None

        return data

    def create(self, **kwargs) -> Account:
        return self.repo.create(**self._normalize_credit_payload(kwargs))

    def list(self, *, user_id: int) -> list[Account]:
        return self.repo.list_by_user(user_id)

    def list_with_last_transaction(self, *, user_id: int) -> list[Account]:
        return self.repo.list_by_user_with_last_transaction(user_id)

    def get(self, *, account_id: int, user_id: int) -> Account:
        account = self.repo.get_by_id_and_user(account_id, user_id)
        if not account:
            raise AccountNotFoundError("Account not found")
        return account

    def update(self, *, account_id: int, user_id: int, **kwargs) -> Account:
        return self.repo.update(self.get(account_id=account_id, user_id=user_id), **self._normalize_credit_payload(kwargs))

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
