"""Credit-payment split for the import pipeline (spec §9).

A credit payment in a bank statement (e.g. «Ежемесячный платёж по кредиту»)
is committed as TWO separate transactions, NOT one:

  1. Interest expense  — `operation_type='regular'`, category=«Проценты по
     кредитам», `credit_account_id` set, `is_regular=True`. Hits the Базовый
     Поток (§CLAUDE.md "Credit Payment Model").
  2. Principal transfer — `operation_type='transfer'`, `target_account_id`
     = loan account, `affects_analytics=False`. Reduces debt balance, NOT
     in expense metrics.

`operation_type='credit_payment'` is **forbidden** (spec §9.1, §12.3).

Extracted from `import_service.commit_import` 2026-04-29 as the first step of
the §1 backlog item «разбивка god-object». Pure logic — DB writes still go
through `TransactionService.create_transaction` so balance/analytics rules
remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.category import Category
from app.services.category_service import CategoryService
from app.services.transaction_service import TransactionService


_INTEREST_CATEGORY_NAME = "Проценты по кредитам"


class CreditSplitError(RuntimeError):
    """Raised when credit-split cannot be applied — surfaced to the import
    moderator UI as a row-level error, not a silent drop."""


@dataclass(frozen=True)
class CreditSplitResult:
    transactions_created: int  # 2 on full split, 1 on fallback
    last_transaction: Any      # Transaction model — for `created_transaction_id` linking


class CreditSplitService:
    """Owns the §9 credit-split logic — interest + principal halves of a
    monthly credit payment.

    Created per import commit; re-uses the caller's DB session so the split
    happens inside the same transaction as the rest of `commit_import`.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.transaction_service = TransactionService(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def commit_split(
        self,
        *,
        user_id: int,
        base_payload: dict[str, Any],
    ) -> CreditSplitResult:
        """Split `base_payload` into interest + principal transactions and
        commit both. Returns the count and the last-created TX (for row-link).

        `base_payload` is the upstream commit payload (the same dict the
        moderator collects from the user). The split logic mutates copies,
        never the original.

        Raises `CreditSplitError` when:
          • the system "Проценты по кредитам" category is missing AND
            re-seeding via `CategoryService.ensure_default_categories`
            doesn't produce one (auto-heal failed).
        """
        principal = base_payload.get("credit_principal_amount")
        interest = base_payload.get("credit_interest_amount")
        eff_credit_acc = (
            base_payload.get("credit_account_id")
            or base_payload.get("target_account_id")
        )

        interest_cat_id = self._resolve_interest_category_id(user_id=user_id)

        if (
            principal is not None
            and interest is not None
            and eff_credit_acc
        ):
            return self._commit_full_split(
                user_id=user_id,
                base_payload=base_payload,
                principal=principal,
                interest=interest,
                eff_credit_acc=eff_credit_acc,
                interest_cat_id=interest_cat_id,
            )
        return self._commit_fallback(
            user_id=user_id,
            base_payload=base_payload,
            eff_credit_acc=eff_credit_acc,
            interest_cat_id=interest_cat_id,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_interest_category_id(self, *, user_id: int) -> int:
        """Find the user's «Проценты по кредитам» system category. If absent,
        re-run `ensure_default_categories` — covers users created before the
        category seeder existed (migration 0036 predecessors).
        """
        cat = self._fetch_interest_category(user_id=user_id)
        if cat is None:
            CategoryService(self.db).ensure_default_categories(user_id=user_id)
            cat = self._fetch_interest_category(user_id=user_id)
        if cat is None:
            raise CreditSplitError(
                "Системная категория «Проценты по кредитам» недоступна — "
                "credit-split не может быть применён. Сообщи в поддержку.",
            )
        return cat.id

    def _fetch_interest_category(self, *, user_id: int) -> Category | None:
        return (
            self.db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.is_system.is_(True),
                Category.name == _INTEREST_CATEGORY_NAME,
            )
            .first()
        )

    def _commit_full_split(
        self,
        *,
        user_id: int,
        base_payload: dict[str, Any],
        principal: Decimal | str | float,
        interest: Decimal | str | float,
        eff_credit_acc: int,
        interest_cat_id: int,
    ) -> CreditSplitResult:
        """Two transactions: interest expense + principal transfer."""
        base_description = base_payload.get("description") or ""

        interest_payload = {
            **base_payload,
            "operation_type": "regular",
            "type": "expense",
            "amount": interest,
            "category_id": interest_cat_id,
            "target_account_id": None,
            "credit_account_id": eff_credit_acc,
            "credit_principal_amount": None,
            "credit_interest_amount": None,
            "description": f"Проценты · {base_description}".strip(" ·"),
        }
        principal_payload = {
            **base_payload,
            "operation_type": "transfer",
            "type": "expense",
            "amount": principal,
            "category_id": None,
            "target_account_id": eff_credit_acc,
            "credit_account_id": eff_credit_acc,
            "credit_principal_amount": None,
            "credit_interest_amount": None,
            "description": f"Тело кредита · {base_description}".strip(" ·"),
        }

        int_tx = self.transaction_service.create_transaction(
            user_id=user_id, payload=interest_payload,
        )
        self.transaction_service.create_transaction(
            user_id=user_id, payload=principal_payload,
        )
        return CreditSplitResult(transactions_created=2, last_transaction=int_tx)

    def _commit_fallback(
        self,
        *,
        user_id: int,
        base_payload: dict[str, Any],
        eff_credit_acc: int | None,
        interest_cat_id: int,
    ) -> CreditSplitResult:
        """Missing principal/interest split values → single interest-style
        expense flagged `needs_review` so the user finishes the split later.
        """
        fallback_payload = {
            **base_payload,
            "operation_type": "regular",
            "type": "expense",
            "category_id": interest_cat_id,
            "target_account_id": None,
            "credit_account_id": eff_credit_acc,
            "needs_review": True,
            "credit_principal_amount": None,
            "credit_interest_amount": None,
        }
        tx = self.transaction_service.create_transaction(
            user_id=user_id, payload=fallback_payload,
        )
        return CreditSplitResult(transactions_created=1, last_transaction=tx)
