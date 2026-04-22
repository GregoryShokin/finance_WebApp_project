"""Layer 2: bank-specific mechanics for import classification.

Each bank has known quirks that go beyond generic account-type inference
(Layer 1). This service encodes those quirks as deterministic rules keyed
by `bank_code`.

Rules are matched against the cluster skeleton (already lowercased,
punctuation stripped, identifiers replaced with placeholders) and direction.

Outputs per cluster:
  - `operation_type` — stronger hint than Layer 1 (bank-confirmed pattern)
  - `category_name`  — suggested category name (resolved to id by caller)
  - `label`          — human-readable reason shown in UI
  - `cross_session_warning` — non-empty when this cluster is likely to be
    duplicated in another of the user's import sessions (e.g., Yandex debit
    payment that also appears in the Yandex Split credit statement).

Cross-session detection is intentionally shallow — we flag the risk and let
the user decide, rather than silently suppressing rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.import_session import ImportSession
from app.repositories.account_repository import AccountRepository


@dataclass(frozen=True)
class _BankRule:
    """A single bank-specific pattern rule."""
    skeleton_keywords: tuple[str, ...]  # any-of match against skeleton
    direction: str | None               # "income" / "expense" / None (any)
    operation_type: str | None
    category_name: str | None           # name to look up in user's categories
    label: str
    account_type_filter: tuple[str, ...] | None = None  # None = any

    def matches(self, skeleton: str, direction: str, account_type: str) -> bool:
        if self.direction and direction != self.direction:
            return False
        if self.account_type_filter and account_type not in self.account_type_filter:
            return False
        return any(kw in skeleton for kw in self.skeleton_keywords)


@dataclass
class BankMechanicsResult:
    """Outcome of bank-mechanics analysis for one cluster."""
    operation_type: str | None = None
    category_name: str | None = None
    label: str | None = None
    cross_session_warning: str | None = None
    confidence_boost: float = 0.0  # added to base confidence when rule fires


# ---------------------------------------------------------------------------
# Per-bank rule tables
# Each tuple is (_BankRule, confidence_boost). Higher boost = more certain.
# ---------------------------------------------------------------------------

_YANDEX_RULES: list[tuple[_BankRule, float]] = [
    # Credit/Split account: purchases via BNPL
    (_BankRule(
        skeleton_keywords=("оплата товаров", "оплата услуг"),
        direction="expense",
        account_type_filter=("credit", "credit_card", "installment_card"),
        operation_type="regular",
        category_name=None,
        label="Яндекс Сплит: покупка в кредит",
    ), 0.05),
    # Credit account: interest payment — highest priority
    (_BankRule(
        skeleton_keywords=("погашение процентов", "проценты пользование", "проценты договору"),
        direction="expense",
        account_type_filter=("credit", "credit_card", "installment_card"),
        operation_type="regular",
        category_name="Проценты по кредитам",
        label="Яндекс: процентная часть платежа по кредиту",
    ), 0.08),
    # Credit account: principal repayment
    (_BankRule(
        skeleton_keywords=("погашение основного долга", "погашение просроченной", "погашение тела", "основного долга"),
        direction="expense",
        account_type_filter=("credit", "credit_card", "installment_card"),
        operation_type="transfer",
        category_name=None,
        label="Яндекс: погашение тела долга",
    ), 0.08),
    # Debit account: outgoing payment that also appears in Split credit statement
    (_BankRule(
        skeleton_keywords=("погашение", "оплата по договору", "перевод по договору"),
        direction="expense",
        account_type_filter=("regular", "credit_card"),
        operation_type="transfer",
        category_name=None,
        label="Яндекс: платёж по кредитному договору (проверь дубль в Сплит)",
    ), 0.05),
    # Cancellations / returns on credit account
    (_BankRule(
        skeleton_keywords=("отмена по операции", "отмена операции", "возврат по операции"),
        direction="income",
        account_type_filter=None,
        operation_type="refund",
        category_name=None,
        label="Яндекс: отмена / возврат",
    ), 0.06),
]

_TBANK_RULES: list[tuple[_BankRule, float]] = [
    # Internal T-Bank transfers (contract in skeleton)
    (_BankRule(
        skeleton_keywords=("перевод по договору", "внутрибанковский перевод", "перевод между счетами"),
        direction=None,
        account_type_filter=None,
        operation_type="transfer",
        category_name=None,
        label="Т-Банк: внутрибанковский перевод",
    ), 0.06),
    # Interest income on deposits
    (_BankRule(
        skeleton_keywords=("проценты по вкладу", "начисление процентов", "капитализация"),
        direction="income",
        account_type_filter=("deposit",),
        operation_type="regular",
        category_name="Проценты от вклада",
        label="Т-Банк: проценты по вкладу",
    ), 0.08),
    # Credit payment
    (_BankRule(
        skeleton_keywords=("погашение кредита", "ежемесячный платеж", "оплата по кредиту"),
        direction="expense",
        account_type_filter=("regular",),
        operation_type="transfer",
        category_name=None,
        label="Т-Банк: платёж по кредиту (проверь дубль в кредитной выписке)",
    ), 0.06),
]

_OZON_RULES: list[tuple[_BankRule, float]] = [
    # Ozon cashback
    (_BankRule(
        skeleton_keywords=("кэшбэк", "cashback", "возврат баллов", "начисление баллов"),
        direction="income",
        account_type_filter=None,
        operation_type="refund",
        category_name="Кэшбэк",
        label="Озон: кэшбэк / возврат баллов",
    ), 0.07),
    # OzonPay marketplace payment
    (_BankRule(
        skeleton_keywords=("ozon", "озон", "маркетплейс", "marketplace"),
        direction="expense",
        account_type_filter=None,
        operation_type="regular",
        category_name=None,
        label="Озон: покупка на маркетплейсе",
    ), 0.04),
]

_SBER_RULES: list[tuple[_BankRule, float]] = [
    (_BankRule(
        skeleton_keywords=("автоплатеж", "autopayment", "регулярный платеж"),
        direction="expense",
        account_type_filter=None,
        operation_type="regular",
        category_name=None,
        label="Сбер: автоплатёж",
    ), 0.04),
    (_BankRule(
        skeleton_keywords=("проценты по вкладу", "начисление", "капитализация"),
        direction="income",
        account_type_filter=("deposit",),
        operation_type="regular",
        category_name="Проценты от вклада",
        label="Сбер: проценты по вкладу",
    ), 0.07),
]

_ALFA_RULES: list[tuple[_BankRule, float]] = [
    (_BankRule(
        skeleton_keywords=("кэшбэк", "cashback"),
        direction="income",
        account_type_filter=None,
        operation_type="refund",
        category_name="Кэшбэк",
        label="Альфа: кэшбэк",
    ), 0.07),
]

BANK_RULES: dict[str, list[tuple[_BankRule, float]]] = {
    "yandex":     _YANDEX_RULES,
    "tbank":      _TBANK_RULES,
    "ozon":       _OZON_RULES,
    "sber":       _SBER_RULES,
    "alfa":       _ALFA_RULES,
}


class BankMechanicsService:
    """Applies bank-specific mechanics to a cluster.

    Call `apply(cluster_data, account, session)` — returns a
    `BankMechanicsResult` with hints that supplement Layer 1 context.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self._account_repo = AccountRepository(db)

    def apply(
        self,
        *,
        skeleton: str,
        direction: str,
        bank_code: str | None,
        account: Account | None,
        session: ImportSession,
        total_amount: Decimal,
    ) -> BankMechanicsResult:
        """Match bank rules and check cross-session risk."""
        if not bank_code or not account:
            return BankMechanicsResult()

        rules = BANK_RULES.get(bank_code, [])
        account_type = str(getattr(account, "account_type", "") or "")

        result = BankMechanicsResult()
        for rule, boost in rules:
            if rule.matches(skeleton, direction, account_type):
                result = BankMechanicsResult(
                    operation_type=rule.operation_type,
                    category_name=rule.category_name,
                    label=rule.label,
                    confidence_boost=boost,
                )
                break  # first matching rule wins

        # Cross-session risk: does a sibling account from the same bank exist
        # that might have the same transaction in its statement?
        warning = self._cross_session_risk(
            bank_code=bank_code,
            account=account,
            direction=direction,
            skeleton=skeleton,
            user_id=session.user_id,
            current_session_id=session.id,
        )
        result = BankMechanicsResult(
            operation_type=result.operation_type,
            category_name=result.category_name,
            label=result.label,
            confidence_boost=result.confidence_boost,
            cross_session_warning=warning,
        )
        return result

    def _cross_session_risk(
        self,
        *,
        bank_code: str,
        account: Account,
        direction: str,
        skeleton: str,
        user_id: int,
        current_session_id: int,
    ) -> str | None:
        """Detect likely double-counting across two statements of the same bank.

        Two patterns are detected:

        A) DEBIT → CREDIT: an expense leaving a debit account of bank X may
           also appear as a repayment on the credit account of the same bank.
           Example: Яндекс Дебет "Погашение" → Яндекс Сплит "Погашение ...".

        B) CREDIT → DEBIT: a "Погашение" expense on the credit account was
           funded by an outgoing payment from the debit account of the same
           bank. The debit statement would have captured that payment too.
           Example: Яндекс Сплит "Погашение процентов" → Яндекс Дебет had
           the same amount going out.

        In both cases we flag the risk; the user decides whether to exclude,
        mark as transfer, or import both (if different economic events).
        """
        _CROSS_SESSION_KEYWORDS = (
            "погашение", "оплата по договору", "перевод по договору",
        )
        if direction != "expense":
            return None
        if not any(kw in skeleton for kw in _CROSS_SESSION_KEYWORDS):
            return None

        from app.models.bank import Bank

        account_type = str(getattr(account, "account_type", "") or "")
        is_credit = bool(getattr(account, "is_credit", False))

        if is_credit or account_type in ("credit", "credit_card", "installment_card"):
            # Pattern B: we are on the credit account — look for a sibling
            # DEBIT account of the same bank that may have captured the same
            # outgoing payment.
            sibling = (
                self.db.query(Account)
                .join(Bank, Account.bank_id == Bank.id, isouter=True)
                .filter(
                    Account.user_id == user_id,
                    Account.id != account.id,
                    Bank.code == bank_code,
                    Account.is_credit.is_(False),
                )
                .first()
            )
            if sibling is None:
                return None
            return (
                f"⚠ Это погашение может уже учтено в выписке «{sibling.name}» "
                f"как исходящий платёж. Проверь — не импортируй дважды."
            )

        # Pattern A: debit account — look for a sibling credit account.
        sibling = (
            self.db.query(Account)
            .join(Bank, Account.bank_id == Bank.id, isouter=True)
            .filter(
                Account.user_id == user_id,
                Account.id != account.id,
                Bank.code == bank_code,
                Account.is_credit.is_(True),
            )
            .first()
        )
        if sibling is None:
            return None
        return (
            f"⚠ Эта операция может дублироваться в выписке «{sibling.name}». "
            f"Отметь как перевод или исключи одну из двух."
        )
