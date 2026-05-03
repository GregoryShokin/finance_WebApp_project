from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction


class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalize_kwargs(kwargs: dict) -> dict:
        data = dict(kwargs)

        # Совместимость между разными версиями полей кредита.
        aliases = {
            "credit_limit_original": "credit_limit_original",
            "credit_current_amount": "credit_current_amount",
            "credit_interest_rate": "credit_interest_rate",
            "credit_term_remaining": "credit_term_remaining",
            "principal_original": "credit_limit_original",
            "principal_current": "credit_current_amount",
            "interest_rate": "credit_interest_rate",
            "remaining_term_months": "credit_term_remaining",
        }

        for source_key, target_key in aliases.items():
            if source_key in data and target_key not in data:
                data[target_key] = data[source_key]

        return data

    @staticmethod
    def _assign_known_fields(account: Account, data: dict) -> None:
        normalized = AccountRepository._normalize_kwargs(data)
        for key, value in normalized.items():
            if hasattr(account, key):
                setattr(account, key, value)

    def create(self, auto_commit: bool = True, **kwargs) -> Account:
        account = Account()
        self._assign_known_fields(account, kwargs)
        self.db.add(account)
        if auto_commit:
            self.db.commit()
            self.db.refresh(account)
        else:
            self.db.flush()
        return account

    def list_by_user(self, user_id: int) -> list[Account]:
        return self.db.query(Account).filter(Account.user_id == user_id).order_by(Account.id.desc()).all()

    def list_by_user_with_last_transaction(self, user_id: int) -> list[Account]:
        rows = (
            self.db.query(
                Account,
                func.max(Transaction.transaction_date).label("last_transaction_date"),
            )
            .outerjoin(Transaction, Transaction.account_id == Account.id)
            .filter(Account.user_id == user_id)
            .group_by(Account.id)
            .order_by(Account.id.desc())
            .all()
        )

        accounts: list[Account] = []
        for account, last_transaction_date in rows:
            setattr(account, "last_transaction_date", last_transaction_date)
            accounts.append(account)
        return accounts

    def find_by_contract_number(
        self,
        user_id: int,
        contract_number: str,
        exclude_account_id: int | None = None,
    ) -> Account | None:
        """Find an account by contract number using a three-level lookup.

        Level 1 — Account.contract_number (fast, indexed).
        Level 2 — parse_settings.contract_number of active import sessions
                  (PDF extracted the contract into the session header).
        Level 3 — tokens.contract inside import_rows of active sessions
                  (contract appears in transaction descriptions, not PDF header;
                   covers Ozon Bank and other banks that omit it from the header).

        `exclude_account_id` filters out the caller's own account so the lookup
        always returns the COUNTERPART account, not the one we already know.
        """
        def _load(account_id: int) -> Account | None:
            filters = [
                Account.id == account_id,
                Account.user_id == user_id,
                Account.is_active == True,
            ]
            if exclude_account_id is not None:
                filters.append(Account.id != exclude_account_id)
            return self.db.query(Account).filter(*filters).first()

        # Level 1: committed Account.contract_number (indexed, fast path).
        base_filters = [
            Account.user_id == user_id,
            Account.contract_number == contract_number,
            Account.is_active == True,
        ]
        if exclude_account_id is not None:
            base_filters.append(Account.id != exclude_account_id)
        account = self.db.query(Account).filter(*base_filters).first()
        if account is not None:
            return account

        from app.models.import_session import ImportSession  # local to avoid circular import

        active_sessions = (
            self.db.query(ImportSession)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportSession.account_id.isnot(None),
            )
            .all()
        )
        if exclude_account_id is not None:
            active_sessions = [s for s in active_sessions if s.account_id != exclude_account_id]

        # Level 2: parse_settings.contract_number (PDF header extraction).
        for sess in active_sessions:
            ps: dict = sess.parse_settings or {}
            if ps.get("contract_number") == contract_number:
                result = _load(sess.account_id)
                if result is not None:
                    return result

        # Level 3: tokens.contract inside import_rows (description extraction).
        # Covers banks whose PDF headers don't carry the contract number but whose
        # transaction descriptions do (e.g. Ozon Bank: «по договору №2025-11-27-KK»).
        from sqlalchemy import text as _sa_text
        session_ids = [s.id for s in active_sessions]
        if not session_ids:
            return None
        row = self.db.execute(
            _sa_text(
                "SELECT DISTINCT s.account_id "
                "FROM import_rows r "
                "JOIN import_sessions s ON s.id = r.session_id "
                "WHERE s.id = ANY(:sids) "
                "  AND r.normalized_data_json -> 'tokens' ->> 'contract' = :cn "
                "LIMIT 1"
            ),
            {"sids": session_ids, "cn": contract_number},
        ).fetchone()
        if row is not None:
            return _load(int(row[0]))

        return None

    def find_by_statement_account_number(self, user_id: int, statement_account_number: str) -> Account | None:
        return (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.statement_account_number == statement_account_number,
                Account.is_active == True,
            )
            .first()
        )

    def get_by_id_and_user(self, account_id: int, user_id: int) -> Account | None:
        return self.db.query(Account).filter(Account.id == account_id, Account.user_id == user_id).first()

    def get_by_id_and_user_for_update(self, account_id: int, user_id: int) -> Account | None:
        return (
            self.db.query(Account)
            .filter(Account.id == account_id, Account.user_id == user_id)
            .with_for_update()
            .first()
        )

    def get_many_by_ids_and_user_for_update(self, *, account_ids: list[int], user_id: int) -> list[Account]:
        if not account_ids:
            return []
        return (
            self.db.query(Account)
            .filter(Account.user_id == user_id, Account.id.in_(account_ids))
            .order_by(Account.id.asc())
            .with_for_update()
            .all()
        )

    def update(self, account: Account, auto_commit: bool = True, **kwargs) -> Account:
        self._assign_known_fields(account, kwargs)
        self.db.add(account)
        if auto_commit:
            self.db.commit()
            self.db.refresh(account)
        else:
            self.db.flush()
        return account

    def delete(self, account: Account, auto_commit: bool = True) -> None:
        self.db.delete(account)
        if auto_commit:
            self.db.commit()
        else:
            self.db.flush()
