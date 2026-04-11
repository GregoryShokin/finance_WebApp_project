from __future__ import annotations
from decimal import Decimal

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.account_repository import AccountRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.counterparty_repository import CounterpartyRepository
from app.repositories.transaction_repository import TransactionRepository
from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository

try:
    from app.services.goal_service import GoalService, GoalValidationError as _GoalValidationError
    _GOALS_AVAILABLE = True
except Exception:
    _GOALS_AVAILABLE = False
    _GoalValidationError = Exception  # type: ignore

try:
    from app.services.transaction_enrichment_service import TransactionEnrichmentService
except Exception:
    class TransactionEnrichmentService:
        def __init__(self, db):
            self.db = db

        @classmethod
        def normalize_description(cls, value):
            return value

        @classmethod
        def normalize_for_rule(cls, value):
            return value


class TransactionConflictError(Exception):
    pass


class TransactionNotFoundError(Exception):
    pass


class TransactionValidationError(Exception):
    pass


NON_ANALYTICS_OPERATION_TYPES = {
    "transfer",
    "investment_buy",
    "investment_sell",
    "credit_disbursement",
    "credit_early_repayment",
    "debt",
}

# Account types that support credit_payment and deferred purchase attribution.
CREDIT_ACCOUNT_TYPES_WITH_DEFERRED = {"credit", "installment_card"}
# All credit account types (used for credit_payment validation).
ALL_CREDIT_ACCOUNT_TYPES = {"credit", "credit_card", "installment_card"}


class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.transaction_repo = TransactionRepository(db)
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.counterparty_repo = CounterpartyRepository(db)
        self.enrichment_service = TransactionEnrichmentService(db)
        self.category_rule_repo = TransactionCategoryRuleRepository(db)

    def list_transactions(
        self,
        *,
        user_id: int,
        account_id: int | None = None,
        category_id: int | None = None,
        category_priority: str | None = None,
        type: str | None = None,
        operation_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        needs_review: bool | None = None,
    ) -> list[Transaction]:
        return self.transaction_repo.list_transactions(
            user_id=user_id,
            account_id=account_id,
            category_id=category_id,
            category_priority=category_priority,
            type=type,
            operation_type=operation_type,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            needs_review=needs_review,
        )

    def create_transaction(self, *, user_id: int, payload: dict[str, Any]) -> Transaction:
        account_id = payload.get("account_id")
        if account_id is None:
            raise TransactionValidationError("РќРµ СѓРєР°Р·Р°РЅ СЃС‡РµС‚ СЃРїРёСЃР°РЅРёСЏ/Р·Р°С‡РёСЃР»РµРЅРёСЏ.")

        payload["user_id"] = user_id
        payload = self._prepare_payload(payload)
        self._validate_payload(user_id=user_id, payload=payload)

        account = self.account_repo.get_by_id_and_user_for_update(account_id, user_id)
        if not account:
            raise TransactionValidationError("РЎС‡РµС‚ РЅРµ РЅР°Р№РґРµРЅ.")

        target_account = self._get_target_account_for_create(user_id=user_id, payload=payload, source_account=account)

        is_deferred = bool(payload.get("is_deferred_purchase", False))
        is_large = bool(payload.get("is_large_purchase", False))

        payload["affects_analytics"] = self._affects_analytics(
            payload.get("operation_type"),
            is_deferred_purchase=is_deferred,
            is_large_purchase=is_large,
        )

        # Initialise deferred_remaining_amount for deferred purchases.
        if is_deferred:
            payload["deferred_remaining_amount"] = payload.get("amount")

        payload.pop("user_id", None)
        transaction = self.transaction_repo.create(auto_commit=False, user_id=user_id, **payload)
        self._apply_balance_effect_on_create(transaction=transaction, account=account, target_account=target_account)

        # For credit/installment accounts: process attribution on credit_payment,
        # and handle early repayment attribution if deferred purchases exist.
        credit_account_id = transaction.credit_account_id or transaction.target_account_id
        if credit_account_id is not None:
            credit_account = self.account_repo.get_by_id_and_user_for_update(credit_account_id, user_id)
            credit_account_type = getattr(credit_account, "account_type", None) if credit_account else None

            if (
                transaction.operation_type == "credit_payment"
                and credit_account_type in CREDIT_ACCOUNT_TYPES_WITH_DEFERRED
            ):
                # Exclude the raw credit_payment from analytics; impact flows through attribution records.
                transaction.affects_analytics = False
                self.db.add(transaction)
                self.db.flush()  # Ensure transaction.id is set before creating attribution records.

                deferred = self._get_active_deferred_purchases(credit_account_id)
                principal = transaction.credit_principal_amount or transaction.amount
                self._create_principal_attributions(
                    payment=transaction,
                    deferred_purchases=deferred,
                    principal_amount=principal,
                    user_id=user_id,
                )
                self._create_interest_expense(payment=transaction, user_id=user_id)

            elif (
                transaction.operation_type == "credit_early_repayment"
                and credit_account_type in CREDIT_ACCOUNT_TYPES_WITH_DEFERRED
            ):
                # Early repayment: attribute to deferred purchases if any exist.
                deferred = self._get_active_deferred_purchases(credit_account_id)
                if deferred:
                    self.db.flush()  # Ensure transaction.id is available.
                    self._create_principal_attributions(
                        payment=transaction,
                        deferred_purchases=deferred,
                        principal_amount=transaction.amount,
                        user_id=user_id,
                    )
                    transaction.is_large_purchase = True
                    self.db.add(transaction)
                # If no deferred purchases: already excluded by NON_ANALYTICS_OPERATION_TYPES.

        # Check goal achievement after linking transaction to goal
        if _GOALS_AVAILABLE and transaction.goal_id is not None:
            GoalService(self.db).check_and_achieve(transaction.goal_id, user_id)

        self._upsert_category_rule_from_payload(user_id=user_id, payload=payload)
        self.db.commit()
        self.db.refresh(transaction)
        return self.transaction_repo.get_by_id(transaction_id=transaction.id, user_id=user_id) or transaction

    def update_transaction(self, *, user_id: int, transaction_id: int, updates: dict[str, Any]) -> Transaction:
        transaction = self.transaction_repo.get_by_id_for_update(transaction_id=transaction_id, user_id=user_id)
        if not transaction:
            raise TransactionNotFoundError("РўСЂР°РЅР·Р°РєС†РёСЏ РЅРµ РЅР°Р№РґРµРЅР°")

        old_account = self.account_repo.get_by_id_and_user_for_update(transaction.account_id, user_id)
        if not old_account:
            raise TransactionValidationError("РЎС‡РµС‚ С‚СЂР°РЅР·Р°РєС†РёРё РЅРµ РЅР°Р№РґРµРЅ.")

        old_target_account = None
        if transaction.target_account_id is not None:
            old_target_account = self.account_repo.get_by_id_and_user_for_update(transaction.target_account_id, user_id)

        effective = self._build_effective_update_payload(transaction=transaction, updates=updates)

        # Р›СЋР±РѕРµ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёРµ СѓР¶Рµ РїРѕРґС‚РІРµСЂР¶РґС‘РЅРЅРѕР№ С‚СЂР°РЅР·Р°РєС†РёРё РґРѕР»Р¶РЅРѕ СЃРЅРѕРІР° РѕС‚РїСЂР°РІР»СЏС‚СЊ РµС‘
        # РЅР° РїСЂРѕРІРµСЂРєСѓ. РћР±СЂР°С‚РЅС‹Р№ РїРµСЂРµРІРѕРґ РІ "Р“РѕС‚РѕРІРѕ" СЂР°Р·СЂРµС€Р°РµРј С‚РѕР»СЊРєРѕ РґР»СЏ С‚СЂР°РЅР·Р°РєС†РёР№,
        # РєРѕС‚РѕСЂС‹Рµ СѓР¶Рµ РЅР°С…РѕРґСЏС‚СЃСЏ РІ СЃС‚Р°С‚СѓСЃРµ needs_review=True, РЅР°РїСЂРёРјРµСЂ С‡РµСЂРµР· РєРЅРѕРїРєСѓ
        # РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ РЅР° СЃС‚СЂР°РЅРёС†Рµ review.
        if transaction.needs_review:
            if "needs_review" not in updates:
                effective["needs_review"] = True
        else:
            effective["needs_review"] = True

        effective["user_id"] = user_id
        effective = self._prepare_payload(effective)

        # Preserve deferred/large flags — they are not changeable via update.
        _is_deferred = bool(getattr(transaction, "is_deferred_purchase", False))
        _is_large = bool(getattr(transaction, "is_large_purchase", False))
        effective["affects_analytics"] = self._affects_analytics(
            effective["operation_type"],
            is_deferred_purchase=_is_deferred,
            is_large_purchase=_is_large,
        )

        self._validate_payload(user_id=user_id, payload=effective)

        new_account = self.account_repo.get_by_id_and_user_for_update(effective["account_id"], user_id)
        if not new_account:
            raise TransactionValidationError("РќРѕРІС‹Р№ СЃС‡РµС‚ С‚СЂР°РЅР·Р°РєС†РёРё РЅРµ РЅР°Р№РґРµРЅ.")

        new_target_account = self._get_target_account_for_create(user_id=user_id, payload=effective, source_account=new_account)

        # Reverse any existing attribution records before modifying the payment.
        old_op = transaction.operation_type
        if old_op in {"credit_payment", "credit_early_repayment"}:
            self._reverse_payment_attributions(payment_id=transaction.id, user_id=user_id)

        self._revert_balance_effect(transaction=transaction, account=old_account, target_account=old_target_account)
        effective.pop("user_id", None)
        updated = self.transaction_repo.update(transaction, auto_commit=False, **effective)
        self._apply_balance_effect_on_create(transaction=updated, account=new_account, target_account=new_target_account)

        # Re-create attributions with the updated payment amounts.
        new_op = updated.operation_type
        credit_account_id = updated.credit_account_id or updated.target_account_id
        if new_op in {"credit_payment", "credit_early_repayment"} and credit_account_id is not None:
            credit_account = self.account_repo.get_by_id_and_user_for_update(credit_account_id, user_id)
            credit_account_type = getattr(credit_account, "account_type", None) if credit_account else None
            if (
                new_op == "credit_payment"
                and credit_account_type in CREDIT_ACCOUNT_TYPES_WITH_DEFERRED
            ):
                updated.affects_analytics = False
                self.db.add(updated)
                self.db.flush()
                deferred = self._get_active_deferred_purchases(credit_account_id)
                principal = updated.credit_principal_amount or updated.amount
                self._create_principal_attributions(
                    payment=updated, deferred_purchases=deferred,
                    principal_amount=principal, user_id=user_id,
                )
                self._create_interest_expense(payment=updated, user_id=user_id)
            elif (
                new_op == "credit_early_repayment"
                and credit_account_type in CREDIT_ACCOUNT_TYPES_WITH_DEFERRED
            ):
                deferred = self._get_active_deferred_purchases(credit_account_id)
                if deferred:
                    self.db.flush()
                    self._create_principal_attributions(
                        payment=updated, deferred_purchases=deferred,
                        principal_amount=updated.amount, user_id=user_id,
                    )

        # Check goal achievement after update
        if _GOALS_AVAILABLE and updated.goal_id is not None:
            GoalService(self.db).check_and_achieve(updated.goal_id, user_id)

        self._upsert_category_rule_from_payload(user_id=user_id, payload=effective)
        self.db.commit()
        self.db.refresh(updated)
        return self.transaction_repo.get_by_id(transaction_id=updated.id, user_id=user_id) or updated


    def _upsert_category_rule_from_payload(self, *, user_id: int, payload: dict[str, Any]) -> None:
        category_id = payload.get("category_id")
        operation_type = payload.get("operation_type")
        normalized_description = payload.get("normalized_description") or self.enrichment_service.normalize_for_rule(payload.get("description"))
        original_description = payload.get("description")

        if not category_id or not normalized_description:
            return
        if operation_type in NON_ANALYTICS_OPERATION_TYPES:
            return

        self.category_rule_repo.upsert(
            user_id=user_id,
            normalized_description=str(normalized_description),
            category_id=int(category_id),
            original_description=(str(original_description) if original_description is not None else None),
        )

    def _build_effective_update_payload(self, *, transaction: Transaction, updates: dict[str, Any]) -> dict[str, Any]:
        """РЎРѕР±РёСЂР°РµС‚ РёС‚РѕРіРѕРІС‹Р№ payload РґР»СЏ update Р±РµР· Р·Р°С‚РёСЂР°РЅРёСЏ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹С… РїРѕР»РµР№ РІ None.

        Р’ review/import frontend РёРЅРѕРіРґР° РѕС‚РїСЂР°РІР»СЏРµС‚ explicit null РґР»СЏ РїРѕР»РµР№, РєРѕС‚РѕСЂС‹Рµ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ
        С„Р°РєС‚РёС‡РµСЃРєРё РЅРµ РјРµРЅСЏР». Р”Р»СЏ NOT NULL РїРѕР»РµР№ СЌС‚Рѕ РїСЂРёРІРѕРґРёР»Рѕ Рє IntegrityError РЅР° flush.
        """

        def pick(key: str, current: Any, *, allow_none: bool = False) -> Any:
            if key not in updates:
                return current
            value = updates[key]
            if value is None and not allow_none:
                return current
            return value

        operation_type = pick("operation_type", transaction.operation_type)

        # credit_account_id вЂ” РєР°РЅРѕРЅРёС‡РµСЃРєРѕРµ РїРѕР»Рµ РґР»СЏ РєСЂРµРґРёС‚РѕРІ. Р”Р»СЏ РѕР±СЂР°С‚РЅРѕР№ СЃРѕРІРјРµСЃС‚РёРјРѕСЃС‚Рё
        # РїРѕРґРґРµСЂР¶РёРІР°РµРј target_account_id, РїРѕС‚РѕРјСѓ С‡С‚Рѕ С‡Р°СЃС‚СЊ СЃС‚Р°СЂРѕРіРѕ UI СЂР°Р±РѕС‚Р°Р»Р° С‚РѕР»СЊРєРѕ СЃ РЅРёРј.
        explicit_credit_account_id = updates.get("credit_account_id") if "credit_account_id" in updates else None
        explicit_target_account_id = updates.get("target_account_id") if "target_account_id" in updates else None

        if operation_type in {"credit_payment", "credit_early_repayment"}:
            resolved_credit_account_id = (
                explicit_credit_account_id
                if explicit_credit_account_id is not None
                else explicit_target_account_id
                if explicit_target_account_id is not None
                else transaction.credit_account_id
                if transaction.credit_account_id is not None
                else transaction.target_account_id
            )
            resolved_target_account_id = resolved_credit_account_id
        else:
            resolved_credit_account_id = pick("credit_account_id", transaction.credit_account_id, allow_none=True)
            resolved_target_account_id = pick("target_account_id", transaction.target_account_id, allow_none=True)

        return {
            "account_id": pick("account_id", transaction.account_id),
            "target_account_id": resolved_target_account_id,
            "credit_account_id": resolved_credit_account_id,
            "category_id": pick("category_id", transaction.category_id, allow_none=True),
            "counterparty_id": pick("counterparty_id", transaction.counterparty_id, allow_none=True),
            "goal_id": pick("goal_id", getattr(transaction, "goal_id", None), allow_none=True),
            "amount": pick("amount", transaction.amount),
            "credit_principal_amount": pick("credit_principal_amount", transaction.credit_principal_amount, allow_none=True),
            "credit_interest_amount": pick("credit_interest_amount", transaction.credit_interest_amount, allow_none=True),
            "debt_direction": pick("debt_direction", getattr(transaction, "debt_direction", None), allow_none=True),
            "currency": pick("currency", transaction.currency),
            "type": pick("type", transaction.type),
            "operation_type": operation_type,
            "description": pick("description", transaction.description, allow_none=True),
            "transaction_date": pick("transaction_date", transaction.transaction_date),
            "needs_review": pick("needs_review", transaction.needs_review),
        }

    def delete_transaction(self, *, transaction_id: int, user_id: int) -> dict[str, str]:
        transaction = self.transaction_repo.get_by_id_for_update(transaction_id=transaction_id, user_id=user_id)
        if not transaction:
            raise TransactionNotFoundError("РўСЂР°РЅР·Р°РєС†РёСЏ РЅРµ РЅР°Р№РґРµРЅР°")

        account = self.account_repo.get_by_id_and_user_for_update(transaction.account_id, user_id)
        if not account:
            raise TransactionValidationError("РЎС‡РµС‚ РЅРµ РЅР°Р№РґРµРЅ")

        # Reverse any attribution/interest records linked to this payment before deleting it.
        if transaction.operation_type in {"credit_payment", "credit_early_repayment"}:
            self._reverse_payment_attributions(payment_id=transaction.id, user_id=user_id)

        pair_id = getattr(transaction, "transfer_pair_id", None)
        if pair_id is not None:
            # Paired transfer: each record owns only its own side of the balance effect.
            pair_tx = self.transaction_repo.get_by_id_for_update(transaction_id=pair_id, user_id=user_id)
            pair_account = (
                self.account_repo.get_by_id_and_user_for_update(pair_tx.account_id, user_id)
                if pair_tx is not None
                else None
            )

            # Revert own balance side
            if transaction.type == "expense":
                account.balance += transaction.amount
            else:
                account.balance -= transaction.amount
            self.db.add(account)

            # Revert pair balance side
            if pair_tx is not None and pair_account is not None:
                if pair_tx.type == "expense":
                    pair_account.balance += pair_tx.amount
                else:
                    pair_account.balance -= pair_tx.amount
                self.db.add(pair_account)

            # Null out cross-references before deleting to avoid FK conflicts
            transaction.transfer_pair_id = None
            if pair_tx is not None:
                pair_tx.transfer_pair_id = None
                self.db.add(pair_tx)
            self.db.flush()

            self.transaction_repo.delete(transaction, auto_commit=False)
            if pair_tx is not None:
                self.transaction_repo.delete(pair_tx, auto_commit=False)
        else:
            target_account = None
            if transaction.target_account_id is not None:
                target_account = self.account_repo.get_by_id_and_user_for_update(transaction.target_account_id, user_id)
                if target_account is None:
                    raise TransactionValidationError("РЎС‡РµС‚ РЅР°Р·РЅР°С‡РµРЅРёСЏ РЅРµ РЅР°Р№РґРµРЅ")
            self._revert_balance_effect(transaction=transaction, account=account, target_account=target_account)
            self.transaction_repo.delete(transaction, auto_commit=False)

        self.db.commit()
        return {"status": "success"}


    def split_transaction(self, *, user_id: int, transaction_id: int, items: list[dict[str, Any]]) -> list[Transaction]:
        transaction = self.transaction_repo.get_by_id_for_update(transaction_id=transaction_id, user_id=user_id)
        if not transaction:
            raise TransactionNotFoundError("РўСЂР°РЅР·Р°РєС†РёСЏ РЅРµ РЅР°Р№РґРµРЅР°")

        if transaction.operation_type != "regular":
            raise TransactionValidationError("Р Р°Р·Р±РёРІР°С‚СЊ РјРѕР¶РЅРѕ С‚РѕР»СЊРєРѕ РѕР±С‹С‡РЅС‹Рµ С‚СЂР°РЅР·Р°РєС†РёРё.")

        if len(items) < 2:
            raise TransactionValidationError("РќСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РјРёРЅРёРјСѓРј РґРІРµ С‡Р°СЃС‚Рё РґР»СЏ СЂР°Р·Р±РёРІРєРё.")

        account = self.account_repo.get_by_id_and_user_for_update(transaction.account_id, user_id)
        if not account:
            raise TransactionValidationError("РЎС‡РµС‚ С‚СЂР°РЅР·Р°РєС†РёРё РЅРµ РЅР°Р№РґРµРЅ.")

        original_amount = transaction.amount
        total_amount = sum(item.get("amount", 0) for item in items)
        if total_amount != original_amount:
            raise TransactionValidationError("РЎСѓРјРјР° С‡Р°СЃС‚РµР№ РґРѕР»Р¶РЅР° Р±С‹С‚СЊ СЂР°РІРЅР° СЃСѓРјРјРµ РёСЃС…РѕРґРЅРѕР№ С‚СЂР°РЅР·Р°РєС†РёРё.")

        prepared_items: list[dict[str, Any]] = []
        for item in items:
            category_id = item.get("category_id")
            amount = item.get("amount")
            if category_id is None:
                raise TransactionValidationError("Р”Р»СЏ РєР°Р¶РґРѕР№ С‡Р°СЃС‚Рё СЂР°Р·Р±РёРІРєРё РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РєР°С‚РµРіРѕСЂРёСЋ.")
            if amount is None or amount <= 0:
                raise TransactionValidationError("РЎСѓРјРјР° РєР°Р¶РґРѕР№ С‡Р°СЃС‚Рё СЂР°Р·Р±РёРІРєРё РґРѕР»Р¶РЅР° Р±С‹С‚СЊ Р±РѕР»СЊС€Рµ РЅСѓР»СЏ.")

            payload = {
                "account_id": transaction.account_id,
                "target_account_id": None,
                "category_id": category_id,
                "amount": amount,
                "currency": transaction.currency,
                "type": transaction.type,
                "operation_type": transaction.operation_type,
                "description": item.get("description") or transaction.description,
                "transaction_date": transaction.transaction_date,
                "needs_review": False,
            }
            payload = self._prepare_payload(payload)
            payload["affects_analytics"] = self._affects_analytics(payload.get("operation_type"))
            self._validate_payload(user_id=user_id, payload=payload)
            prepared_items.append(payload)

        self._revert_balance_effect(transaction=transaction, account=account, target_account=None)
        self.transaction_repo.delete(transaction, auto_commit=False)

        created_ids: list[int] = []
        for payload in prepared_items:
            created = self.transaction_repo.create(auto_commit=False, user_id=user_id, **payload)
            self._apply_balance_effect_on_create(transaction=created, account=account, target_account=None)
            created_ids.append(created.id)

        self.db.commit()
        return [
            self.transaction_repo.get_by_id(transaction_id=created_id, user_id=user_id)
            for created_id in created_ids
            if self.transaction_repo.get_by_id(transaction_id=created_id, user_id=user_id) is not None
        ]

    def delete_transactions_by_period(
        self,
        *,
        user_id: int,
        date_from: datetime,
        date_to: datetime,
        account_id: int | None = None,
    ) -> int:
        if date_to < date_from:
            raise TransactionValidationError("РљРѕРЅРµС‡РЅР°СЏ РґР°С‚Р° РїРµСЂРёРѕРґР° РЅРµ РјРѕР¶РµС‚ Р±С‹С‚СЊ СЂР°РЅСЊС€Рµ РЅР°С‡Р°Р»СЊРЅРѕР№.")

        transactions = self.transaction_repo.get_for_period_for_update(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            account_id=account_id,
        )
        if not transactions:
            return 0

        account_ids = {item.account_id for item in transactions}
        account_ids.update(item.target_account_id for item in transactions if item.target_account_id is not None)
        accounts = self.account_repo.get_many_by_ids_and_user_for_update(account_ids=list(account_ids), user_id=user_id)
        accounts_by_id = {account.id: account for account in accounts}

        for transaction in transactions:
            source_account = accounts_by_id.get(transaction.account_id)
            if source_account is None:
                raise TransactionValidationError(f"РќРµ РЅР°Р№РґРµРЅ СЃС‡С‘С‚ {transaction.account_id} РґР»СЏ СѓРґР°Р»РµРЅРёСЏ РїРµСЂРёРѕРґР°.")
            target_account = accounts_by_id.get(transaction.target_account_id) if transaction.target_account_id is not None else None
            self._revert_balance_effect(transaction=transaction, account=source_account, target_account=target_account)
            self.transaction_repo.delete(transaction, auto_commit=False)

        self.db.commit()
        return len(transactions)

    def _prepare_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(payload)
        description = prepared.get("description")
        operation_type = prepared.get("operation_type")
        counterparty_id = prepared.get("counterparty_id")
        if operation_type == "debt" and counterparty_id not in (None, "", 0):
            counterparty = self.counterparty_repo.get_by_id_and_user(int(counterparty_id), int(prepared.get("user_id") or 0)) if prepared.get("user_id") else None
            if counterparty is not None and not str(description or "").strip():
                prepared["description"] = counterparty.name
                description = counterparty.name
        prepared["normalized_description"] = self.enrichment_service.normalize_for_rule(description)
        return prepared

    def _validate_payload(self, *, user_id: int, payload: dict[str, Any]) -> None:
        operation_type = payload.get("operation_type")
        target_account_id = payload.get("target_account_id")
        category_id = payload.get("category_id")
        counterparty_id = payload.get("counterparty_id")
        transaction_type = payload.get("type")
        debt_direction = payload.get("debt_direction")

        # Validate goal_id if provided
        goal_id = payload.get("goal_id")
        if goal_id is not None and _GOALS_AVAILABLE:
            try:
                GoalService(self.db).validate_goal_for_transaction(int(goal_id), user_id)
            except _GoalValidationError as exc:
                raise TransactionValidationError(str(exc)) from exc

        allow_incomplete_transfer = bool(payload.get("needs_review"))

        if operation_type == "transfer":
            if target_account_id is None and not allow_incomplete_transfer:
                raise TransactionValidationError("Р”Р»СЏ РїРµСЂРµРІРѕРґР° РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ СЃС‡РµС‚ РЅР°Р·РЅР°С‡РµРЅРёСЏ.")
            if category_id is not None:
                raise TransactionValidationError("Р”Р»СЏ РїРµСЂРµРІРѕРґР° РЅРµР»СЊР·СЏ СѓРєР°Р·С‹РІР°С‚СЊ РєР°С‚РµРіРѕСЂРёСЋ.")
        elif operation_type in {"credit_payment", "credit_early_repayment"}:
            if target_account_id is None and not allow_incomplete_transfer:
                raise TransactionValidationError("Для платежа по кредиту нужно указать кредит.")
            if category_id is not None:
                raise TransactionValidationError("Для платежа по кредиту нельзя указывать категорию.")
        elif target_account_id is not None:
            raise TransactionValidationError("РЎС‡РµС‚ РЅР°Р·РЅР°С‡РµРЅРёСЏ РјРѕР¶РЅРѕ СѓРєР°Р·С‹РІР°С‚СЊ С‚РѕР»СЊРєРѕ РґР»СЏ РїРµСЂРµРІРѕРґР° Рё РїР»Р°С‚РµР¶Р° РїРѕ РєСЂРµРґРёС‚Сѓ.")

        if operation_type == "debt":
            if counterparty_id in (None, "", 0):
                raise TransactionValidationError("Р”Р»СЏ РґРѕР»РіР° РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ РєРѕРЅС‚СЂР°РіРµРЅС‚Р°.")
            if debt_direction not in {"lent", "borrowed", "repaid", "collected"}:
                raise TransactionValidationError("Р”Р»СЏ РґРѕР»РіР° РЅСѓР¶РЅРѕ РІС‹Р±СЂР°С‚СЊ РєРѕСЂСЂРµРєС‚РЅРѕРµ РЅР°РїСЂР°РІР»РµРЅРёРµ.")
        elif counterparty_id not in (None, "", 0):
            raise TransactionValidationError("РљРѕРЅС‚СЂР°РіРµРЅС‚Р° РјРѕР¶РЅРѕ СѓРєР°Р·С‹РІР°С‚СЊ С‚РѕР»СЊРєРѕ РґР»СЏ РѕРїРµСЂР°С†РёР№ С‚РёРїР° РґРѕР»Рі.")

        if counterparty_id not in (None, "", 0):
            counterparty = self.counterparty_repo.get_by_id_and_user(int(counterparty_id), user_id)
            if counterparty is None:
                raise TransactionValidationError("РљРѕРЅС‚СЂР°РіРµРЅС‚ РЅРµ РЅР°Р№РґРµРЅ.")

        if category_id is None:
            return

        category = self._get_category(category_id=category_id, user_id=user_id)
        if category is None:
            raise TransactionValidationError("РљР°С‚РµРіРѕСЂРёСЏ РЅРµ РЅР°Р№РґРµРЅР°.")

        if transaction_type is not None and category.kind != transaction_type and operation_type != "refund":
            raise TransactionValidationError("РўРёРї С‚СЂР°РЅР·Р°РєС†РёРё РЅРµ СЃРѕРІРїР°РґР°РµС‚ СЃ С‚РёРїРѕРј РІС‹Р±СЂР°РЅРЅРѕР№ РєР°С‚РµРіРѕСЂРёРё.")

    def _get_category(self, *, category_id: int, user_id: int) -> Category | None:
        return self.category_repo.get_by_id(category_id=category_id, user_id=user_id)

    def _get_target_account_for_create(
        self,
        *,
        user_id: int,
        payload: dict[str, Any],
        source_account: Account,
    ) -> Account | None:
        target_account_id = payload.get("target_account_id")
        operation_type = payload.get("operation_type")

        if operation_type not in {"transfer", "credit_payment", "credit_early_repayment"}:
            return None

        if target_account_id is None:
            if payload.get("needs_review"):
                return None
            if operation_type in {"credit_payment", "credit_early_repayment"}:
                raise TransactionValidationError("Для платежа по кредиту нужно указать кредит.")
            raise TransactionValidationError("Р”Р»СЏ РїРµСЂРµРІРѕРґР° РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ СЃС‡РµС‚ РЅР°Р·РЅР°С‡РµРЅРёСЏ.")

        if target_account_id == source_account.id:
            raise TransactionValidationError("РЎС‡РµС‚ СЃРїРёСЃР°РЅРёСЏ Рё СЃС‡РµС‚ РЅР°Р·РЅР°С‡РµРЅРёСЏ РЅРµ РґРѕР»Р¶РЅС‹ СЃРѕРІРїР°РґР°С‚СЊ.")

        target_account = self.account_repo.get_by_id_and_user_for_update(target_account_id, user_id)
        if not target_account:
            raise TransactionValidationError("РЎС‡РµС‚ РЅР°Р·РЅР°С‡РµРЅРёСЏ РЅРµ РЅР°Р№РґРµРЅ.")
        if operation_type in {"credit_payment", "credit_early_repayment"}:
            acct_type = getattr(target_account, "account_type", None)
            is_credit = bool(getattr(target_account, "is_credit", False))
            if acct_type not in ALL_CREDIT_ACCOUNT_TYPES and not is_credit:
                raise TransactionValidationError(
                    "Для платежа по кредиту нужно выбрать кредитный счёт или кредитную карту."
                )

        return target_account

    @staticmethod
    def _affects_analytics(
        operation_type: str | None,
        *,
        is_deferred_purchase: bool = False,
        is_large_purchase: bool = False,
    ) -> bool:
        # Deferred and large-purchase transactions are excluded from the normal
        # expense analytics; their impact is recognized through attribution records
        # (deferred) or shown only in the Large Purchases section (large).
        if is_deferred_purchase or is_large_purchase:
            return False
        # Attribution expense records are always in analytics (affects_analytics
        # is set explicitly to True when they are created, not via this method).
        return operation_type not in NON_ANALYTICS_OPERATION_TYPES

    # ------------------------------------------------------------------
    # Deferred purchase attribution helpers
    # ------------------------------------------------------------------

    def _get_active_deferred_purchases(self, credit_account_id: int) -> list[Transaction]:
        """Return deferred purchases with remaining principal > 0 for the account."""
        from decimal import Decimal as _D
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.account_id == credit_account_id,
                Transaction.is_deferred_purchase.is_(True),
                Transaction.deferred_remaining_amount > _D("0"),
            )
            .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
            .all()
        )

    def _create_principal_attributions(
        self,
        *,
        payment: Transaction,
        deferred_purchases: list[Transaction],
        principal_amount: Decimal,
        user_id: int,
    ) -> None:
        """Distribute principal proportionally across active deferred purchases.

        For each purchase, creates a credit_principal_attribution expense
        transaction (affects_analytics=True) and decrements
        deferred_remaining_amount accordingly.
        """
        if not deferred_purchases or principal_amount <= Decimal("0"):
            return

        total_remaining = sum(
            (p.deferred_remaining_amount or Decimal("0")) for p in deferred_purchases
        )
        if total_remaining <= Decimal("0"):
            return

        allocated: list[tuple[Transaction, Decimal]] = []
        running_total = Decimal("0")

        for purchase in deferred_purchases:
            remaining = purchase.deferred_remaining_amount or Decimal("0")
            ratio = remaining / total_remaining
            # Floor to whole rubles
            share = (principal_amount * ratio).to_integral_value(rounding="ROUND_FLOOR")
            allocated.append((purchase, share))
            running_total += share

        # Add rounding remainder to the largest share
        rounding_diff = principal_amount - running_total
        if rounding_diff > Decimal("0") and allocated:
            largest_idx = max(
                range(len(allocated)), key=lambda i: allocated[i][0].deferred_remaining_amount or Decimal("0")
            )
            purchase, share = allocated[largest_idx]
            allocated[largest_idx] = (purchase, share + rounding_diff)

        for purchase, share in allocated:
            if share <= Decimal("0"):
                continue
            attribution = Transaction(
                user_id=user_id,
                account_id=payment.account_id,
                category_id=purchase.category_id,
                amount=share,
                currency=payment.currency,
                type="expense",
                operation_type="credit_principal_attribution",
                affects_analytics=True,
                transaction_date=payment.transaction_date,
                source_payment_id=payment.id,
                description=f"Платёж по кредиту: {purchase.description or 'без описания'}",
            )
            self.db.add(attribution)
            # Decrement remaining amount on the deferred purchase
            current_remaining = purchase.deferred_remaining_amount or Decimal("0")
            purchase.deferred_remaining_amount = max(Decimal("0"), current_remaining - share)
            self.db.add(purchase)

    def _create_interest_expense(
        self,
        *,
        payment: Transaction,
        user_id: int,
    ) -> None:
        """Create an expense record for the interest portion of a credit payment."""
        interest = payment.credit_interest_amount
        if not interest or interest <= Decimal("0"):
            return

        from app.services.category_service import CategoryService
        interest_category = CategoryService(self.db).get_or_create_interest_category(user_id=user_id)

        interest_tx = Transaction(
            user_id=user_id,
            account_id=payment.account_id,
            category_id=interest_category.id,
            amount=interest,
            currency=payment.currency,
            type="expense",
            operation_type="credit_interest",
            affects_analytics=True,
            transaction_date=payment.transaction_date,
            source_payment_id=payment.id,
            description="Проценты по кредиту",
        )
        self.db.add(interest_tx)

    def _reverse_payment_attributions(
        self,
        *,
        payment_id: int,
        user_id: int,
    ) -> None:
        """Delete attribution/interest records for a payment and restore remaining amounts."""
        attributions = (
            self.db.query(Transaction)
            .filter(
                Transaction.source_payment_id == payment_id,
                Transaction.user_id == user_id,
            )
            .all()
        )
        for attr in attributions:
            if attr.operation_type == "credit_principal_attribution":
                # Restore the deferred_remaining_amount on the linked deferred purchase.
                # The link is via category_id and timing — approximate restoration.
                # Full integrity: find the deferred purchase by matching account + category
                # that still has a balance and is within a sensible date range.
                # Simple approach: add the amount back to any open deferred purchase
                # with the same category on the same credit account.
                deferred = (
                    self.db.query(Transaction)
                    .filter(
                        Transaction.account_id == attr.account_id,
                        Transaction.is_deferred_purchase.is_(True),
                        Transaction.category_id == attr.category_id,
                        Transaction.user_id == user_id,
                    )
                    .order_by(Transaction.transaction_date.asc())
                    .first()
                )
                if deferred is not None:
                    current = deferred.deferred_remaining_amount or Decimal("0")
                    cap = deferred.amount  # cannot exceed original amount
                    deferred.deferred_remaining_amount = min(current + attr.amount, cap)
                    self.db.add(deferred)
            self.db.delete(attr)

    def check_large_purchase(self, *, user_id: int, amount: Decimal) -> dict:
        """Return whether `amount` exceeds the user's large-purchase threshold."""
        from app.services.user_settings_service import UserSettingsService
        from app.services.metrics_service import MetricsService

        settings = UserSettingsService(self.db).get_or_default(user_id)
        metrics = MetricsService(self.db)
        avg_expenses = metrics.get_avg_monthly_expenses(user_id=user_id)
        threshold = (avg_expenses * settings.large_purchase_threshold_pct).quantize(
            Decimal("0.01")
        )
        return {
            "is_large": amount >= threshold,
            "threshold_amount": float(threshold),
            "avg_monthly_expenses": float(avg_expenses),
        }

    def _apply_balance_effect_on_create(
        self,
        *,
        transaction: Transaction,
        account: Account,
        target_account: Account | None,
    ) -> None:
        if transaction.operation_type == "transfer":
            account.balance -= transaction.amount
            if target_account is not None:
                target_account.balance += transaction.amount
                self.db.add(target_account)
        elif transaction.operation_type in {"credit_payment", "credit_early_repayment"}:
            account.balance -= transaction.amount
            if target_account is not None:
                if getattr(target_account, "account_type", None) == "credit_card":
                    target_account.balance += transaction.amount
                else:
                    current_amount = getattr(target_account, "credit_current_amount", None)
                    if current_amount is None:
                        current_amount = Decimal("0")
                    principal_amount = transaction.credit_principal_amount
                    if principal_amount is None:
                        principal_amount = transaction.amount
                    next_amount = current_amount - principal_amount
                    if next_amount < 0:
                        next_amount = Decimal("0")
                    target_account.credit_current_amount = next_amount
                    target_account.balance = -next_amount
                self.db.add(target_account)
        elif transaction.type == "expense":
            account.balance -= transaction.amount
        elif transaction.type == "income":
            account.balance += transaction.amount

        self.db.add(account)

    def _revert_balance_effect(
        self,
        *,
        transaction: Transaction,
        account: Account,
        target_account: Account | None,
    ) -> None:
        if transaction.operation_type == "transfer":
            account.balance += transaction.amount
            if target_account is not None:
                target_account.balance -= transaction.amount
                self.db.add(target_account)
        elif transaction.operation_type in {"credit_payment", "credit_early_repayment"}:
            account.balance += transaction.amount
            if target_account is not None:
                if getattr(target_account, "account_type", None) == "credit_card":
                    target_account.balance -= transaction.amount
                else:
                    current_amount = getattr(target_account, "credit_current_amount", None)
                    if current_amount is None:
                        current_amount = Decimal("0")
                    principal_amount = transaction.credit_principal_amount
                    if principal_amount is None:
                        principal_amount = transaction.amount
                    next_amount = current_amount + principal_amount
                    target_account.credit_current_amount = next_amount
                    target_account.balance = -next_amount
                self.db.add(target_account)
        elif transaction.type == "expense":
            account.balance += transaction.amount
        elif transaction.type == "income":
            account.balance -= transaction.amount

        self.db.add(account)
