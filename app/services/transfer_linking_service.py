"""Transfer-pair linking and creation for the import pipeline (spec §10.6, §10.7, §12.9, §12.12).

Three branches at commit time, all of which keep the user's account balances
and the `transfer_pair_id` invariant intact:

1. **`create_transfer_pair`** — both sides are NEW. Creates two TransactionModel
   rows (one per account), links them, applies balance to BOTH accounts.

2. **`link_to_committed_orphan`** — partner side is already committed as
   orphan / regular (target_account_id IS NULL). Creates ONLY the active side,
   upgrades the orphan in-place (target/operation/affects_analytics, sets
   transfer_pair_id on both), applies balance to the active account ONLY (the
   orphan's balance was already applied at its earlier commit).
   See spec §10.6 / §12.9.

3. **`link_to_committed_cross_session_phantom`** — both sides were active in
   different ImportSessions; partner committed first via
   `create_transfer_pair`, which created BOTH sides (incl. a "phantom" TX on
   our account). We just return that phantom — caller links the import row to
   it without creating a second pair (would double-credit balances).
   See spec §10.7 / §12.12.

Extracted from `import_service.py` 2026-04-29 as step 2 of the §1 backlog
god-object decomposition. Pure delegation — DB session is passed in by the
caller; service does not own its own commit boundary EXCEPT inside the three
public methods which finalize their own transaction (matches the legacy inline
behavior in `import_service.commit_import`).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.transaction import Transaction as TransactionModel
from app.repositories.account_repository import AccountRepository


class TransferLinkingError(Exception):
    """Raised when the active transfer side has no usable account on the user."""


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "").replace(",", ".")
        if not cleaned:
            raise ValueError("Пустое значение суммы.")
        return Decimal(cleaned)
    raise TypeError("Некорректный формат суммы.")


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("Некорректный формат даты транзакции.")


class TransferLinkingService:
    """Owns the three transfer-creation/linking branches at commit time.

    The caller (currently `ImportService.commit_import`) decides WHICH branch
    to use based on `normalized.transfer_match` shape. This service just
    executes that branch correctly and atomically.
    """

    def __init__(self, db: Session, *, normalize_description) -> None:
        self.db = db
        self.account_repo = AccountRepository(db)
        # `normalize_description` is a callable from TransactionEnrichmentService.
        # Passed in (not constructed here) so the caller can share its enricher
        # instance and any cached state.
        self._normalize_description = normalize_description

    # ------------------------------------------------------------------
    # Branch 1: both sides new
    # ------------------------------------------------------------------

    def create_transfer_pair(
        self, *, user_id: int, payload: dict[str, Any],
    ) -> tuple[TransactionModel, TransactionModel]:
        """Creates two linked Transfer transactions — one per account side —
        and applies balance effects to both accounts.

        `payload['type']` ∈ {'income', 'expense'} determines which side the
        SESSION account is on; `target_account_id` is the OTHER side.
        """
        account_id = int(payload["account_id"])
        target_account_id = int(payload["target_account_id"])
        amount = _to_decimal(payload["amount"])
        currency = str(payload.get("currency") or "RUB").upper()
        description = (payload.get("description") or "")[:500]
        transaction_date = _to_datetime(payload["transaction_date"])
        needs_review = bool(payload.get("needs_review"))
        normalized_description = self._normalize_description(description)
        skeleton = payload.get("skeleton") or None
        fingerprint = payload.get("fingerprint") or None  # spec §13 v1.20

        tx_type = str(payload.get("type") or "expense")
        if tx_type == "income":
            expense_account_id = target_account_id
            income_account_id = account_id
        else:
            expense_account_id = account_id
            income_account_id = target_account_id

        expense_account = self.account_repo.get_by_id_and_user_for_update(
            expense_account_id, user_id,
        )
        income_account = self.account_repo.get_by_id_and_user_for_update(
            income_account_id, user_id,
        )
        if expense_account is None:
            raise TransferLinkingError("Счёт списания не найден.")
        if income_account is None:
            raise TransferLinkingError("Счёт поступления не найден.")

        t_expense = TransactionModel(
            user_id=user_id,
            account_id=expense_account_id,
            target_account_id=income_account_id,
            amount=amount,
            currency=currency,
            type="expense",
            operation_type="transfer",
            description=description,
            normalized_description=normalized_description,
            skeleton=skeleton,
            fingerprint=fingerprint,
            transaction_date=transaction_date,
            needs_review=needs_review,
            affects_analytics=False,
        )
        self.db.add(t_expense)

        t_income = TransactionModel(
            user_id=user_id,
            account_id=income_account_id,
            target_account_id=expense_account_id,
            amount=amount,
            currency=currency,
            type="income",
            operation_type="transfer",
            description=description,
            normalized_description=normalized_description,
            skeleton=skeleton,
            fingerprint=fingerprint,
            transaction_date=transaction_date,
            needs_review=needs_review,
            affects_analytics=False,
        )
        self.db.add(t_income)

        self.db.flush()  # assign IDs
        t_expense.transfer_pair_id = t_income.id
        t_income.transfer_pair_id = t_expense.id

        expense_account.balance -= amount
        income_account.balance += amount
        self.db.add(expense_account)
        self.db.add(income_account)

        self.db.commit()
        self.db.refresh(t_expense)
        self.db.refresh(t_income)

        return t_expense, t_income

    # ------------------------------------------------------------------
    # Branch 2: link to committed orphan (spec §10.6, §12.9)
    # ------------------------------------------------------------------

    def link_to_committed_orphan(
        self, *, user_id: int, payload: dict[str, Any], committed_tx_id: int,
    ) -> TransactionModel | None:
        """Link the active side to an already-committed orphan transaction.

        Returns the new active TX, or None when linkage is impossible (caller
        falls back to `create_transfer_pair`):
          • committed TX not found / not owned by user
          • committed TX already paired (transfer_pair_id IS NOT NULL)
          • account / amount / direction don't agree with the active side
        """
        committed_tx = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.id == committed_tx_id,
                TransactionModel.user_id == user_id,
            )
            .first()
        )
        if committed_tx is None or committed_tx.transfer_pair_id is not None:
            return None

        active_account_id = int(payload["account_id"])
        active_target_account_id = int(payload["target_account_id"])
        if committed_tx.account_id != active_target_account_id:
            return None

        amount = _to_decimal(payload["amount"])
        if _to_decimal(committed_tx.amount) != amount:
            return None

        active_type = str(payload.get("type") or "expense")
        committed_type = str(committed_tx.type or "")
        if active_type == committed_type:
            return None

        currency = str(payload.get("currency") or "RUB").upper()
        description = (payload.get("description") or "")[:500]
        transaction_date = _to_datetime(payload["transaction_date"])
        needs_review = bool(payload.get("needs_review"))
        normalized_description = self._normalize_description(description)
        skeleton = payload.get("skeleton") or None
        fingerprint = payload.get("fingerprint") or None  # spec §13 v1.20

        active_account = self.account_repo.get_by_id_and_user_for_update(
            active_account_id, user_id,
        )
        if active_account is None:
            raise TransferLinkingError("Счёт активной стороны не найден.")

        active_tx = TransactionModel(
            user_id=user_id,
            account_id=active_account_id,
            target_account_id=active_target_account_id,
            amount=amount,
            currency=currency,
            type=active_type,
            operation_type="transfer",
            description=description,
            normalized_description=normalized_description,
            skeleton=skeleton,
            fingerprint=fingerprint,
            transaction_date=transaction_date,
            needs_review=needs_review,
            affects_analytics=False,
        )
        self.db.add(active_tx)
        self.db.flush()

        committed_tx.target_account_id = active_account_id
        committed_tx.operation_type = "transfer"
        committed_tx.affects_analytics = False
        committed_tx.transfer_pair_id = active_tx.id
        active_tx.transfer_pair_id = committed_tx.id
        self.db.add(committed_tx)
        self.db.add(active_tx)

        # Balance applies ONLY to the active account — the orphan's effect was
        # already applied at its earlier commit.
        if active_type == "expense":
            active_account.balance -= amount
        else:
            active_account.balance += amount
        self.db.add(active_account)

        self.db.commit()
        self.db.refresh(active_tx)
        self.db.refresh(committed_tx)

        return active_tx

    # ------------------------------------------------------------------
    # Branch 3: link to phantom from cross-session partner (spec §10.7, §12.12)
    # ------------------------------------------------------------------

    def link_to_committed_cross_session_phantom(
        self, *, user_id: int, payload: dict[str, Any], matched_import_row_id: int,
    ) -> TransactionModel | None:
        """Find the phantom TX created by the partner row's earlier commit.

        Returns the phantom TX on OUR account side, or None when:
          • partner row not yet committed (caller falls back to create_pair)
          • phantom missing / mismatched

        No DB writes here — the caller links the import row to the returned TX.
        Balance is NOT adjusted (already applied at partner's commit).
        """
        partner_row = (
            self.db.query(ImportRow)
            .filter(ImportRow.id == matched_import_row_id)
            .first()
        )
        if partner_row is None or partner_row.created_transaction_id is None:
            return None

        partner_committed_tx = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.id == partner_row.created_transaction_id,
                TransactionModel.user_id == user_id,
            )
            .first()
        )
        if partner_committed_tx is None or partner_committed_tx.transfer_pair_id is None:
            return None

        our_account_id = int(payload["account_id"])

        if partner_committed_tx.account_id == our_account_id:
            return partner_committed_tx

        sibling_tx = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.id == partner_committed_tx.transfer_pair_id,
                TransactionModel.user_id == user_id,
            )
            .first()
        )
        if sibling_tx is not None and sibling_tx.account_id == our_account_id:
            return sibling_tx

        return None
