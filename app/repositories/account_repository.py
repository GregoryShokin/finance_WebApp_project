from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction


class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalize_kwargs(kwargs: dict) -> dict:
        data = dict(kwargs)

        # Совместимость между разными версиями полей кредита.
        aliases = {
            "credit_limit_original": "credit_limit_original",
            "credit_current_amount": "credit_current_amount",
            "credit_interest_rate": "credit_interest_rate",
            "credit_term_remaining": "credit_term_remaining",
            "principal_original": "credit_limit_original",
            "principal_current": "credit_current_amount",
            "interest_rate": "credit_interest_rate",
            "remaining_term_months": "credit_term_remaining",
        }

        for source_key, target_key in aliases.items():
            if source_key in data and target_key not in data:
                data[target_key] = data[source_key]

        return data

    @staticmethod
    def _assign_known_fields(account: Account, data: dict) -> None:
        normalized = AccountRepository._normalize_kwargs(data)
        for key, value in normalized.items():
            if hasattr(account, key):
                setattr(account, key, value)

    def create(self, auto_commit: bool = True, **kwargs) -> Account:
        account = Account()
        self._assign_known_fields(account, kwargs)
        self.db.add(account)
        if auto_commit:
            self.db.commit()
            self.db.refresh(account)
        else:
            self.db.flush()
        return account

    def list_by_user(self, user_id: int) -> list[Account]:
        return self.db.query(Account).filter(Account.user_id == user_id).order_by(Account.id.desc()).all()

    def list_by_user_with_last_transaction(self, user_id: int) -> list[Account]:
        rows = (
            self.db.query(
                Account,
                func.max(Transaction.transaction_date).label("last_transaction_date"),
            )
            .outerjoin(Transaction, Transaction.account_id == Account.id)
            .filter(Account.user_id == user_id)
            .group_by(Account.id)
            .order_by(Account.id.desc())
            .all()
        )

        accounts: list[Account] = []
        for account, last_transaction_date in rows:
            setattr(account, "last_transaction_date", last_transaction_date)
            accounts.append(account)
        return accounts

    def find_by_contract_number(self, user_id: int, contract_number: str) -> Account | None:
        return (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.contract_number == contract_number,
                Account.is_active == True,
            )
            .first()
        )

    def find_by_statement_account_number(self, user_id: int, statement_account_number: str) -> Account | None:
        return (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.statement_account_number == statement_account_number,
                Account.is_active == True,
            )
            .first()
        )

    def get_by_id_and_user(self, account_id: int, user_id: int) -> Account | None:
        return self.db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()

    def get_by_id_and_user_for_update(self, account_id: int, user_id: int) -> Account | None:
        return (
            self.db.query(Account)
            .filter(Account.id == account_id, Account.user_id == user_id)
            .with_for_update()
            .first()
        )

    def get_many_by_ids_and_user_for_update(self, *, account_ids: list[int], user_id: int) -> list[Account]:
        if not account_ids:
            return []
        return (
            self.db.query(Account)
            .filter(Account.user_id == user_id, Account.id.in_(account_ids))
            .order_by(Account.id.asc())
            .with_for_update()
            .all()
        )

    def update(self, account: Account, auto_commit: bool = True, **kwargs) -> Account:
        self._assign_known_fields(account, kwargs)
        self.db.add(account)
        if auto_commit:
            self.db.commit()
            self.db.refresh(account)
        else:
            self.db.flush()
        return account

    def delete(self, account: Account, auto_commit: bool = True) -> None:
        self.db.delete(account)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
