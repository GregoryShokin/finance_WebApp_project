from __future__ import annotations

from sqlalchemy import func
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

    def get_by_name_ci(self, name: str, user_id: int) -> DebtPartner | None:
        """Case-insensitive lookup — «Брат», «брат» and «БРАТ» resolve to
        the same partner. Used by find_or_create_by_name so the user
        doesn't accidentally create two contacts that differ only by case.
        """
        target = (name or "").strip()
        if not target:
            return None
        return (
            self.db.query(DebtPartner)
            .filter(
                DebtPartner.user_id == user_id,
                func.lower(DebtPartner.name) == target.lower(),
            )
            .first()
        )

    def search_by_name(
        self, *, user_id: int, query: str, limit: int = 20,
    ) -> list[DebtPartner]:
        """Case-insensitive substring search over the user's debt partners.
        Drives the unified «+ Имя / Бренд» picker — results are merged with
        Brand search hits in `ImportService.search_names`.
        """
        q = (query or "").strip()
        if not q:
            return (
                self.db.query(DebtPartner)
                .filter(DebtPartner.user_id == user_id)
                .order_by(DebtPartner.name.asc())
                .limit(limit)
                .all()
            )
        return (
            self.db.query(DebtPartner)
            .filter(
                DebtPartner.user_id == user_id,
                func.lower(DebtPartner.name).like(f"%{q.lower()}%"),
            )
            .order_by(DebtPartner.name.asc())
            .limit(limit)
            .all()
        )

    def find_or_create_by_name(
        self,
        *,
        user_id: int,
        name: str,
        default_category_id: int | None = None,
    ) -> tuple[DebtPartner, bool]:
        """Case-insensitive get-or-create. Returns (partner, created).

        When the partner already exists and `default_category_id` is set,
        we DO NOT overwrite an existing default — the first naming wins.
        Re-binding to a different category is an explicit user action via
        the contact-edit form (out of scope for this picker).
        """
        existing = self.get_by_name_ci(name, user_id)
        if existing is not None:
            return existing, False
        partner = DebtPartner(
            user_id=user_id,
            name=name.strip(),
            default_category_id=default_category_id,
        )
        self.db.add(partner)
        self.db.flush()
        return partner, True

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
