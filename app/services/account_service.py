from decimal import Decimal

from sqlalchemy.orm import Session
from app.models.account import Account
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
        elif account_type == "credit_card":
            if "balance" in data and data.get("balance") is not None:
                data["balance"] = Decimal(str(data["balance"]))
            data["credit_current_amount"] = None
            data["credit_interest_rate"] = None
            data["credit_term_remaining"] = None
        else:
            data["credit_current_amount"] = None
            data["credit_interest_rate"] = None
            data["credit_term_remaining"] = None
            data["credit_limit_original"] = None

        return data

    def create(self, **kwargs) -> Account:
        return self.repo.create(**self._normalize_credit_payload(kwargs))

    def list(self, *, user_id: int) -> list[Account]:
        return self.repo.list_by_user(user_id)

    def get(self, *, account_id: int, user_id: int) -> Account:
        account = self.repo.get_by_id_and_user(account_id, user_id)
        if not account:
            raise AccountNotFoundError("Account not found")
        return account

    def update(self, *, account_id: int, user_id: int, **kwargs) -> Account:
        return self.repo.update(self.get(account_id=account_id, user_id=user_id), **self._normalize_credit_payload(kwargs))

    def delete(self, *, account_id: int, user_id: int) -> None:
        self.repo.delete(self.get(account_id=account_id, user_id=user_id))
