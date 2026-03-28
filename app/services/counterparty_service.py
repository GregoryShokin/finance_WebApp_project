from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.counterparty_repository import CounterpartyRepository


class CounterpartyNotFoundError(Exception):
    pass


class CounterpartyValidationError(Exception):
    pass


class CounterpartyService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CounterpartyRepository(db)

    def list_counterparties(self, *, user_id: int):
        items = self.repo.list_by_user(user_id)
        for item in items:
            receivable = Decimal(str(item.opening_receivable_amount or 0))
            payable = Decimal(str(item.opening_payable_amount or 0))
            for tx in getattr(item, "transactions", []) or []:
                if tx.operation_type != "debt":
                    continue
                direction = getattr(tx, "debt_direction", None) or ("borrowed" if tx.type == "income" else "lent")
                amount = Decimal(str(tx.amount or 0))
                if direction == "lent":
                    receivable += amount
                elif direction == "collected":
                    receivable -= amount
                elif direction == "borrowed":
                    payable += amount
                elif direction == "repaid":
                    payable -= amount
            item.receivable_amount = receivable if receivable > 0 else Decimal("0")
            item.payable_amount = payable if payable > 0 else Decimal("0")
        return items

    def create_counterparty(self, *, user_id: int, payload: dict):
        name = str(payload.get("name") or "").strip()
        if not name:
            raise CounterpartyValidationError("Укажи имя контрагента.")
        if self.repo.get_by_name_and_user(name, user_id):
            raise CounterpartyValidationError("Контрагент с таким именем уже существует.")

        opening_balance = Decimal(str(payload.get("opening_balance") or 0))
        kind = str(payload.get("opening_balance_kind") or "receivable").strip().lower()
        if kind not in {"receivable", "payable"}:
            raise CounterpartyValidationError("Некорректный тип стартового долга.")

        return self.repo.create(
            auto_commit=False,
            user_id=user_id,
            name=name,
            opening_receivable_amount=opening_balance if kind == "receivable" else Decimal("0"),
            opening_payable_amount=opening_balance if kind == "payable" else Decimal("0"),
        )

    def delete_counterparty(self, *, user_id: int, counterparty_id: int):
        item = self.repo.get_by_id_and_user(counterparty_id, user_id)
        if item is None:
            raise CounterpartyNotFoundError("Контрагент не найден.")

        for tx in getattr(item, "transactions", []) or []:
            tx.counterparty_id = None
        self.repo.delete(item, auto_commit=False)
        self.db.commit()
        return {"success": True}
