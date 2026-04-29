from __future__ import annotations

from sqlalchemy.orm import joinedload

from app.models.debt_partner import DebtPartner


class DebtPartnerRepository:
    def __init__(self, db):
        self.db = db

    def list_by_user(self, user_id: int) -> list[DebtPartner]:
        return (
            self.db.query(DebtPartner)
            .options(joinedload(DebtPartner.transactions))
            .filter(DebtPartner.user_id == user_id)
            .order_by(DebtPartner.name.asc(), DebtPartner.id.asc())
            .all()
        )

    def get_by_id_and_user(
        self, partner_id: int, user_id: int,
    ) -> DebtPartner | None:
        return (
            self.db.query(DebtPartner)
            .options(joinedload(DebtPartner.transactions))
            .filter(DebtPartner.id == partner_id, DebtPartner.user_id == user_id)
            .first()
        )

    def get_by_name_and_user(self, name: str, user_id: int) -> DebtPartner | None:
        return (
            self.db.query(DebtPartner)
            .filter(DebtPartner.user_id == user_id, DebtPartner.name == name)
            .first()
        )

    def create(self, *, auto_commit: bool = True, **kwargs) -> DebtPartner:
        item = DebtPartner(**kwargs)
        self.db.add(item)
        self.db.flush()
        if auto_commit:
            self.db.commit()
            self.db.refresh(item)
        return item

    def delete(self, item: DebtPartner, *, auto_commit: bool = True) -> None:
        self.db.delete(item)
        if auto_commit:
            self.db.commit()
