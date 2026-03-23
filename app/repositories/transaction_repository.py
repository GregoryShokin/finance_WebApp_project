from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import joinedload

from app.models.transaction import Transaction


class TransactionRepository:
    def __init__(self, db):
        self.db = db

    def _base_query(self):
        return self.db.query(Transaction).options(
            joinedload(Transaction.account),
            joinedload(Transaction.target_account),
            joinedload(Transaction.category),
        )

    def list_transactions(
        self,
        *,
        user_id: int,
        account_id: int | None = None,
        category_id: int | None = None,
        category_priority: str | None = None,
        type: str | None = None,
        operation_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        needs_review: bool | None = None,
    ) -> list[Transaction]:
        query = self._base_query().filter(Transaction.user_id == user_id)

        if account_id is not None:
            query = query.filter(Transaction.account_id == account_id)
        if category_id is not None:
            query = query.filter(Transaction.category_id == category_id)
        if category_priority is not None:
            query = query.filter(Transaction.category.has(priority=category_priority))
        if type is not None:
            query = query.filter(Transaction.type == type)
        if operation_type is not None:
            query = query.filter(Transaction.operation_type == operation_type)
        if date_from is not None:
            query = query.filter(Transaction.transaction_date >= date_from)
        if date_to is not None:
            query = query.filter(Transaction.transaction_date <= date_to)
        if min_amount is not None:
            query = query.filter(Transaction.amount >= min_amount)
        if max_amount is not None:
            query = query.filter(Transaction.amount <= max_amount)
        if needs_review is not None:
            query = query.filter(Transaction.needs_review == needs_review)

        return query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).all()

    def get_by_id(self, *, transaction_id: int, user_id: int) -> Transaction | None:
        return (
            self._base_query()
            .filter(Transaction.id == transaction_id, Transaction.user_id == user_id)
            .first()
        )

    def get_by_id_for_update(self, *, transaction_id: int, user_id: int) -> Transaction | None:
        return (
            self.db.query(Transaction)
            .filter(Transaction.id == transaction_id, Transaction.user_id == user_id)
            .with_for_update()
            .first()
        )

    def get_for_period_for_update(
        self,
        *,
        user_id: int,
        date_from: datetime,
        date_to: datetime,
        account_id: int | None = None,
    ) -> list[Transaction]:
        query = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .with_for_update()
        )

        if account_id is not None:
            query = query.filter(Transaction.account_id == account_id)

        return query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).all()

    def create(self, *, auto_commit: bool = True, **payload: Any) -> Transaction:
        transaction = Transaction(**payload)
        self.db.add(transaction)
        self.db.flush()

        if auto_commit:
            self.db.commit()
            self.db.refresh(transaction)

        return transaction

    def update(self, transaction: Transaction, *, auto_commit: bool = True, **updates: Any) -> Transaction:
        for key, value in updates.items():
            setattr(transaction, key, value)

        self.db.add(transaction)
        self.db.flush()

        if auto_commit:
            self.db.commit()
            self.db.refresh(transaction)

        return transaction

    def delete(self, transaction: Transaction, *, auto_commit: bool = True) -> None:
        self.db.delete(transaction)

        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()

    def find_possible_duplicate(
        self,
        *,
        user_id: int,
        account_id: int,
        amount,
        transaction_date,
        description: str | None,
    ):
        query = self.db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.account_id == account_id,
            Transaction.amount == amount,
            Transaction.transaction_date == transaction_date,
        )

        if description:
            query = query.filter(Transaction.description == description)

        return query.first()

    def find_nearby_duplicates(
        self,
        *,
        user_id: int,
        account_id: int,
        amount,
        transaction_date,
        description: str | None = None,
        days_window: int = 3,
    ):
        date_from = transaction_date - timedelta(days=days_window)
        date_to = transaction_date + timedelta(days=days_window)

        query = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.account_id == account_id,
                Transaction.amount == amount,
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .order_by(Transaction.transaction_date.desc())
        )

        if description:
            query = query.filter(Transaction.description == description)

        return query.all()
