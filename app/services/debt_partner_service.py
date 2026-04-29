from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.repositories.debt_partner_repository import DebtPartnerRepository


class DebtPartnerNotFoundError(Exception):
    pass


class DebtPartnerValidationError(Exception):
    pass


class DebtPartnerService:
    """Mirrors CounterpartyService but scoped to debt transactions only.

    Balances (receivable = "мне должны", payable = "я должен") are computed
    on read from this partner's debt transactions. Formula matches the one
    CounterpartyService used for debt computations, so migrating existing
    debt counterparties into this table is lossless.
    """

    def __init__(self, db: Session):
        self.db = db
        self.repo = DebtPartnerRepository(db)

    def list_partners(self, *, user_id: int):
        items = self.repo.list_by_user(user_id)
        for item in items:
            receivable = Decimal(str(item.opening_receivable_amount or 0))
            payable = Decimal(str(item.opening_payable_amount or 0))
            for tx in getattr(item, "transactions", []) or []:
                if tx.operation_type != "debt":
                    continue
                direction = getattr(tx, "debt_direction", None) or (
                    "borrowed" if tx.type == "income" else "lent"
                )
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

    def create_partner(self, *, user_id: int, payload: dict):
        name = str(payload.get("name") or "").strip()
        if not name:
            raise DebtPartnerValidationError("Укажи имя дебитора / кредитора.")
        if self.repo.get_by_name_and_user(name, user_id):
            raise DebtPartnerValidationError(
                "Дебитор / кредитор с таким именем уже существует."
            )

        opening_balance = Decimal(str(payload.get("opening_balance") or 0))
        kind = str(payload.get("opening_balance_kind") or "receivable").strip().lower()
        if kind not in {"receivable", "payable"}:
            raise DebtPartnerValidationError("Некорректный тип стартового долга.")

        note = payload.get("note")
        note_str = str(note).strip() if note is not None else None

        return self.repo.create(
            auto_commit=False,
            user_id=user_id,
            name=name,
            opening_receivable_amount=opening_balance if kind == "receivable" else Decimal("0"),
            opening_payable_amount=opening_balance if kind == "payable" else Decimal("0"),
            note=note_str or None,
        )

    def delete_partner(self, *, user_id: int, partner_id: int):
        item = self.repo.get_by_id_and_user(partner_id, user_id)
        if item is None:
            raise DebtPartnerNotFoundError("Дебитор / кредитор не найден.")
        for tx in getattr(item, "transactions", []) or []:
            tx.debt_partner_id = None
        self.repo.delete(item, auto_commit=False)
        self.db.commit()
        return {"success": True}
