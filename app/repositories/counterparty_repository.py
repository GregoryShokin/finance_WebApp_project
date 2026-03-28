from __future__ import annotations

from sqlalchemy.orm import joinedload

from app.models.counterparty import Counterparty


class CounterpartyRepository:
    def __init__(self, db):
        self.db = db

    def list_by_user(self, user_id: int) -> list[Counterparty]:
        return (
            self.db.query(Counterparty)
            .options(joinedload(Counterparty.transactions))
            .filter(Counterparty.user_id == user_id)
            .order_by(Counterparty.name.asc(), Counterparty.id.asc())
            .all()
        )

    def get_by_id_and_user(self, counterparty_id: int, user_id: int) -> Counterparty | None:
        return (
            self.db.query(Counterparty)
            .options(joinedload(Counterparty.transactions))
            .filter(Counterparty.id == counterparty_id, Counterparty.user_id == user_id)
            .first()
        )

    def get_by_name_and_user(self, name: str, user_id: int) -> Counterparty | None:
        return (
            self.db.query(Counterparty)
            .filter(Counterparty.user_id == user_id, Counterparty.name == name)
            .first()
        )

    def create(self, *, auto_commit: bool = True, **kwargs) -> Counterparty:
        item = Counterparty(**kwargs)
        self.db.add(item)
        self.db.flush()
        if auto_commit:
            self.db.commit()
            self.db.refresh(item)
        return item

    def delete(self, item: Counterparty, *, auto_commit: bool = True) -> None:
        self.db.delete(item)
        if auto_commit:
            self.db.commit()
