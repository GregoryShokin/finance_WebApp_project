from sqlalchemy.orm import Session
from app.models.account import Account
from app.repositories.account_repository import AccountRepository


class AccountNotFoundError(Exception):
    pass


class AccountService:
    def __init__(self, db: Session):
        self.repo = AccountRepository(db)

    def create(self, *, user_id: int, name: str, currency: str, balance, is_active: bool = True, is_credit: bool = False) -> Account:
        return self.repo.create(
            user_id=user_id,
            name=name,
            currency=currency,
            balance=balance,
            is_active=is_active,
            is_credit=is_credit,
        )

    def list(self, *, user_id: int) -> list[Account]:
        return self.repo.list_by_user(user_id)

    def get(self, *, account_id: int, user_id: int) -> Account:
        account = self.repo.get_by_id_and_user(account_id, user_id)
        if not account:
            raise AccountNotFoundError("Account not found")
        return account

    def update(self, *, account_id: int, user_id: int, **kwargs) -> Account:
        return self.repo.update(self.get(account_id=account_id, user_id=user_id), **kwargs)

    def delete(self, *, account_id: int, user_id: int) -> None:
        self.repo.delete(self.get(account_id=account_id, user_id=user_id))
