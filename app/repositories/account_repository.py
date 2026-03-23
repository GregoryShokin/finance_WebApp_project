from sqlalchemy.orm import Session

from app.models.account import Account


class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: int,
        name: str,
        currency: str,
        balance,
        is_active: bool = True,
        is_credit: bool = False,
        auto_commit: bool = True,
    ) -> Account:
        account = Account(
            user_id=user_id,
            name=name,
            currency=currency,
            balance=balance,
            is_active=is_active,
            is_credit=is_credit,
        )
        self.db.add(account)
        if auto_commit:
            self.db.commit()
            self.db.refresh(account)
        else:
            self.db.flush()
        return account

    def list_by_user(self, user_id: int) -> list[Account]:
        return self.db.query(Account).filter(Account.user_id == user_id).order_by(Account.id.desc()).all()

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
        for key, value in kwargs.items():
            setattr(account, key, value)
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
