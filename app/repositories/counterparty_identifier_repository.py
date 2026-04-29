from __future__ import annotations

from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from app.models.counterparty_identifier import CounterpartyIdentifier


class CounterpartyIdentifierRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
    ) -> CounterpartyIdentifier | None:
        return (
            self.db.query(CounterpartyIdentifier)
            .filter(
                CounterpartyIdentifier.user_id == user_id,
                CounterpartyIdentifier.identifier_kind == identifier_kind,
                CounterpartyIdentifier.identifier_value == identifier_value,
            )
            .first()
        )

    def list_by_pairs(
        self,
        *,
        user_id: int,
        pairs: list[tuple[str, str]],
    ) -> list[CounterpartyIdentifier]:
        if not pairs:
            return []
        return (
            self.db.query(CounterpartyIdentifier)
            .filter(
                CounterpartyIdentifier.user_id == user_id,
                tuple_(
                    CounterpartyIdentifier.identifier_kind,
                    CounterpartyIdentifier.identifier_value,
                ).in_([(k, v) for k, v in pairs]),
            )
            .all()
        )

    def list_by_counterparty(
        self, *, user_id: int, counterparty_id: int,
    ) -> list[CounterpartyIdentifier]:
        return (
            self.db.query(CounterpartyIdentifier)
            .filter(
                CounterpartyIdentifier.user_id == user_id,
                CounterpartyIdentifier.counterparty_id == counterparty_id,
            )
            .all()
        )

    def upsert(
        self,
        *,
        user_id: int,
        identifier_kind: str,
        identifier_value: str,
        counterparty_id: int,
    ) -> tuple[CounterpartyIdentifier, bool]:
        """Create or strengthen an identifier→counterparty binding.

        Returns (binding, is_new). On conflict the counterparty_id is
        overwritten and confirms incremented — each bulk-apply is an explicit
        vote, so repeated confirmations compound strength.
        """
        binding = self.get(
            user_id=user_id,
            identifier_kind=identifier_kind,
            identifier_value=identifier_value,
        )
        is_new = binding is None
        if binding is None:
            binding = CounterpartyIdentifier(
                user_id=user_id,
                identifier_kind=identifier_kind,
                identifier_value=identifier_value,
                counterparty_id=counterparty_id,
                confirms=1,
            )
            self.db.add(binding)
        else:
            binding.counterparty_id = counterparty_id
            binding.confirms = (binding.confirms or 0) + 1
        self.db.flush()
        return binding, is_new

    def delete(self, *, binding: CounterpartyIdentifier) -> None:
        self.db.delete(binding)
        self.db.flush()
