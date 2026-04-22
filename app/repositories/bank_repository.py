from sqlalchemy.orm import Session
from app.models.bank import Bank


class BankRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[Bank]:
        return self.db.query(Bank).order_by(Bank.is_popular.desc(), Bank.name).all()

    def list_popular(self) -> list[Bank]:
        return self.db.query(Bank).filter(Bank.is_popular.is_(True)).order_by(Bank.name).all()

    def search(self, query: str) -> list[Bank]:
        q = f"%{query.strip().lower()}%"
        return (
            self.db.query(Bank)
            .filter(Bank.name.ilike(q))
            .order_by(Bank.is_popular.desc(), Bank.name)
            .limit(20)
            .all()
        )

    def get_by_id(self, bank_id: int) -> Bank | None:
        return self.db.query(Bank).filter(Bank.id == bank_id).first()

    def get_by_code(self, code: str) -> Bank | None:
        return self.db.query(Bank).filter(Bank.code == code).first()
