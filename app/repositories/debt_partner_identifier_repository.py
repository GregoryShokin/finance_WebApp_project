from __future__ import annotations

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.models.debt_partner_identifier import DebtPartnerIdentifier


class DebtPartnerIdentifierRepository:
    """Mirror of `BrandIdentifierRepository` — same shape, different FK.

    See `app.models.debt_partner_identifier.DebtPartnerIdentifier` for
    semantics. This module owns nothing more than the SQL — service-level
    rules (which kinds are accepted, when binding fires) live in
    `PersonalNameBindService`.
    """

    def __init__(self, db: Session):
        self.db = db

    def get(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
    ) -> DebtPartnerIdentifier | None:
        return (
            self.db.query(DebtPartnerIdentifier)
            .filter(
                DebtPartnerIdentifier.user_id == user_id,
                DebtPartnerIdentifier.identifier_kind == identifier_kind,
                DebtPartnerIdentifier.identifier_value == identifier_value,
            )
            .first()
        )

    def list_by_pairs(
        self,
        *,
        user_id: int,
        pairs: list[tuple[str, str]],
    ) -> list[DebtPartnerIdentifier]:
        if not pairs:
            return []
        return (
            self.db.query(DebtPartnerIdentifier)
            .filter(
                DebtPartnerIdentifier.user_id == user_id,
                tuple_(
                    DebtPartnerIdentifier.identifier_kind,
                    DebtPartnerIdentifier.identifier_value,
                ).in_([(k, v) for k, v in pairs]),
            )
            .all()
        )

    def list_by_debt_partner(
        self, *, user_id: int, debt_partner_id: int,
    ) -> list[DebtPartnerIdentifier]:
        return (
            self.db.query(DebtPartnerIdentifier)
            .filter(
                DebtPartnerIdentifier.user_id == user_id,
                DebtPartnerIdentifier.debt_partner_id == debt_partner_id,
            )
            .all()
        )

    def upsert(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
        debt_partner_id: int,
    ) -> tuple[DebtPartnerIdentifier, bool]:
        """Idempotent bind. If a row already exists for (user, kind, value),
        re-point it at `debt_partner_id` and bump `confirms`. Re-bind is the
        strongest signal a user can give: «no, this phone number is THIS
        person, not the one you guessed last time» — we honour it without a
        second confirmation step.
        """
        binding = self.get(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
        )
        is_new = binding is None
        if binding is None:
            binding = DebtPartnerIdentifier(
                user_id=user_id,
                identifier_kind=identifier_kind,
                identifier_value=identifier_value,
                debt_partner_id=debt_partner_id,
                confirms=1,
            )
            self.db.add(binding)
        else:
            binding.debt_partner_id = debt_partner_id
            binding.confirms = (binding.confirms or 0) + 1
        self.db.flush()
        return binding, is_new

    def delete(self, *, binding: DebtPartnerIdentifier) -> None:
        self.db.delete(binding)
        self.db.flush()
