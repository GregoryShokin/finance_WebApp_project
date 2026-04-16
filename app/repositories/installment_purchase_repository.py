from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.installment_purchase import InstallmentPurchase


class InstallmentPurchaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_account(
        self,
        *,
        account_id: int,
        user_id: int,
        status: str | None = None,
    ) -> list[InstallmentPurchase]:
        query = (
            self.db.query(InstallmentPurchase)
            .join(Account, Account.id == InstallmentPurchase.account_id)
            .filter(
                InstallmentPurchase.account_id == account_id,
                Account.user_id == user_id,
            )
        )
        if status:
            query = query.filter(InstallmentPurchase.status == status)
        return query.order_by(InstallmentPurchase.start_date.desc()).all()

    def get_by_id(self, *, purchase_id: int, user_id: int) -> InstallmentPurchase | None:
        return (
            self.db.query(InstallmentPurchase)
            .join(Account, Account.id == InstallmentPurchase.account_id)
            .filter(
                InstallmentPurchase.id == purchase_id,
                Account.user_id == user_id,
            )
            .first()
        )

    def create(self, **kwargs) -> InstallmentPurchase:
        purchase = InstallmentPurchase(**kwargs)
        self.db.add(purchase)
        self.db.commit()
        self.db.refresh(purchase)
        return purchase

    def update(self, purchase: InstallmentPurchase, **updates) -> InstallmentPurchase:
        for key, value in updates.items():
            if value is not None:
                setattr(purchase, key, value)
        self.db.add(purchase)
        self.db.commit()
        self.db.refresh(purchase)
        return purchase

    def delete(self, purchase: InstallmentPurchase) -> None:
        self.db.delete(purchase)
        self.db.commit()
