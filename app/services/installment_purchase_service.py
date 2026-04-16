from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.installment_purchase import InstallmentPurchase
from app.repositories.account_repository import AccountRepository
from app.repositories.installment_purchase_repository import InstallmentPurchaseRepository


class InstallmentPurchaseNotFoundError(Exception):
    pass


class InstallmentPurchaseValidationError(Exception):
    pass


class InstallmentPurchaseService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = InstallmentPurchaseRepository(db)
        self.account_repo = AccountRepository(db)

    def _validate_account(self, account_id: int, user_id: int):
        account = self.account_repo.get_by_id_and_user(account_id, user_id)
        if not account:
            raise InstallmentPurchaseValidationError("Счёт не найден.")
        if account.account_type != "installment_card":
            raise InstallmentPurchaseValidationError(
                "Покупки в рассрочку можно добавлять только к счетам типа «Карта рассрочки»."
            )
        return account

    def _check_payment_warning(self, account_id: int, user_id: int) -> str | None:
        account = self.account_repo.get_by_id_and_user(account_id, user_id)
        if not account or account.monthly_payment is None:
            return None
        purchases = self.repo.get_by_account(
            account_id=account_id, user_id=user_id, status="active"
        )
        total = sum(Decimal(str(p.monthly_payment)) for p in purchases)
        if total != Decimal(str(account.monthly_payment)):
            return (
                f"Сумма ежемесячных платежей по покупкам ({total} ₽) "
                f"не совпадает с платежом по счёту ({account.monthly_payment} ₽)."
            )
        return None

    def list_purchases(
        self, *, account_id: int, user_id: int
    ) -> tuple[list[InstallmentPurchase], str | None]:
        self._validate_account(account_id, user_id)
        items = self.repo.get_by_account(account_id=account_id, user_id=user_id)
        warning = self._check_payment_warning(account_id, user_id)
        return items, warning

    def get_purchase(
        self, *, purchase_id: int, user_id: int
    ) -> InstallmentPurchase:
        purchase = self.repo.get_by_id(purchase_id=purchase_id, user_id=user_id)
        if not purchase:
            raise InstallmentPurchaseNotFoundError("Покупка не найдена.")
        return purchase

    def create_purchase(
        self, *, account_id: int, user_id: int, data: dict
    ) -> tuple[InstallmentPurchase, str | None]:
        self._validate_account(account_id, user_id)
        data["account_id"] = account_id
        data["remaining_amount"] = data["original_amount"]
        purchase = self.repo.create(**data)
        warning = self._check_payment_warning(account_id, user_id)
        return purchase, warning

    def update_purchase(
        self, *, purchase_id: int, user_id: int, updates: dict
    ) -> tuple[InstallmentPurchase, str | None]:
        purchase = self.get_purchase(purchase_id=purchase_id, user_id=user_id)
        updated = self.repo.update(purchase, **updates)
        warning = self._check_payment_warning(updated.account_id, user_id)
        return updated, warning

    def delete_purchase(self, *, purchase_id: int, user_id: int) -> None:
        purchase = self.get_purchase(purchase_id=purchase_id, user_id=user_id)
        self.repo.delete(purchase)
