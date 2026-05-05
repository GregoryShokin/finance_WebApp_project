from sqlalchemy.orm import Session

from app.models.bank_support_request import BankSupportRequest


class BankSupportRequestRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: int,
        bank_name: str,
        bank_id: int | None = None,
        note: str | None = None,
    ) -> BankSupportRequest:
        req = BankSupportRequest(
            user_id=user_id,
            bank_id=bank_id,
            bank_name=bank_name.strip(),
            note=(note.strip() if note else None) or None,
        )
        self.db.add(req)
        self.db.commit()
        self.db.refresh(req)
        return req

    def list_for_user(self, user_id: int) -> list[BankSupportRequest]:
        return (
            self.db.query(BankSupportRequest)
            .filter(BankSupportRequest.user_id == user_id)
            .order_by(
                BankSupportRequest.created_at.desc(),
                BankSupportRequest.id.desc(),
            )
            .all()
        )

    def find_open_for_user_and_bank(
        self, *, user_id: int, bank_id: int | None, bank_name: str,
    ) -> BankSupportRequest | None:
        """Idempotency helper — open requests are 'pending' or 'in_review'.

        Match by `bank_id` if known, otherwise fall back to case-insensitive
        `bank_name` (free-text bank not in our table).
        """
        builder = self.db.query(BankSupportRequest).filter(
            BankSupportRequest.user_id == user_id,
            BankSupportRequest.status.in_(("pending", "in_review")),
        )
        if bank_id is not None:
            builder = builder.filter(BankSupportRequest.bank_id == bank_id)
        else:
            builder = builder.filter(BankSupportRequest.bank_name.ilike(bank_name.strip()))
        return builder.first()
