from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.counterparty_fingerprint import CounterpartyFingerprint


class CounterpartyFingerprintRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_fingerprint(
        self, *, user_id: int, fingerprint: str
    ) -> CounterpartyFingerprint | None:
        return (
            self.db.query(CounterpartyFingerprint)
            .filter(
                CounterpartyFingerprint.user_id == user_id,
                CounterpartyFingerprint.fingerprint == fingerprint,
            )
            .first()
        )

    def list_by_counterparty(
        self, *, user_id: int, counterparty_id: int
    ) -> list[CounterpartyFingerprint]:
        return (
            self.db.query(CounterpartyFingerprint)
            .filter(
                CounterpartyFingerprint.user_id == user_id,
                CounterpartyFingerprint.counterparty_id == counterparty_id,
            )
            .all()
        )

    def list_by_fingerprints(
        self, *, user_id: int, fingerprints: list[str]
    ) -> list[CounterpartyFingerprint]:
        if not fingerprints:
            return []
        return (
            self.db.query(CounterpartyFingerprint)
            .filter(
                CounterpartyFingerprint.user_id == user_id,
                CounterpartyFingerprint.fingerprint.in_(fingerprints),
            )
            .all()
        )

    def upsert(
        self,
        *,
        user_id: int,
        fingerprint: str,
        counterparty_id: int,
    ) -> tuple[CounterpartyFingerprint, bool]:
        """Create or update a fingerprint→counterparty binding.

        Returns (binding, is_new). If a binding already exists for this
        (user, fingerprint) the counterparty_id is overwritten and
        confirms incremented — treat each bulk-apply as an explicit vote
        so over time the strongest binding wins.
        """
        binding = self.get_by_fingerprint(user_id=user_id, fingerprint=fingerprint)
        is_new = binding is None
        if binding is None:
            binding = CounterpartyFingerprint(
                user_id=user_id,
                fingerprint=fingerprint,
                counterparty_id=counterparty_id,
                confirms=1,
            )
            self.db.add(binding)
        else:
            binding.counterparty_id = counterparty_id
            binding.confirms = (binding.confirms or 0) + 1
        self.db.flush()
        return binding, is_new

    def delete(self, *, binding: CounterpartyFingerprint) -> None:
        self.db.delete(binding)
        self.db.flush()
