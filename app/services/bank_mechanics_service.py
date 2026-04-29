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
    # When True: row is a phantom-mirror of a transfer from the paired debit
    # account and should be auto-excluded so the balance isn't double-counted.
    # Example: Яндекс Сплит income «погашение основного долга» — covered by the
    # phantom income auto-created when the Дебет transfer pair was committed.
    suggest_exclude: bool = False
    # When True: the bank_mechanics layer should attempt to resolve the row's
    # target_account_id from the contract token in normalized_data.tokens.
    suggest_target_by_contract: bool = False

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
    # True → import pipeline should auto-exclude this row (phantom-mirror).
    suggest_exclude: bool = False
    # Non-None → import pipeline should set target_account_id to this value.
    resolved_target_account_id: int | None = None


# ---------------------------------------------------------------------------
# Per-bank rule tables
# Each tuple is (_BankRule, confidence_boost). Higher boost = more certain.
# ---------------------------------------------------------------------------

_YANDEX_RULES: list[tuple[_BankRule, float]] = [
    # ── Яндекс Сплит (credit/installment) — income direction ────────────────
    #
    # P-02 fix: когда с Яндекс Дебета переводится платёж по кредиту,
    # на Сплит приходит income. Эти строки НЕ создают новые транзакции —
    # они либо покрыты phantom-income от Дебет-перевода (основной долг),
    # либо должны быть учтены как расход «Проценты по кредитам» (проценты).
    #
    # «Погашение основного долга» income → suggest_exclude=True.
    # Phantom income уже создан _create_transfer_pair при коммите Дебет-стороны.
    # Если закоммитить ещё и эту строку — баланс Сплит-счёта будет задвоен.
    (_BankRule(
        skeleton_keywords=(
            "погашение основного долга",
            "погашение просроченной",
            "погашение тела",
            "основного долга",
        ),
        direction="income",
        account_type_filter=("loan", "credit_card", "installment_card"),
        operation_type=None,
        category_name=None,
        label="Яндекс Сплит: поступление в счёт тела кредита — дубль Дебет-перевода",
        suggest_exclude=True,
    ), 0.18),
    # «Погашение процентов» income → regular expense «Проценты по кредитам».
    # Деньги пришли на Сплит с Дебета специально для оплаты процентов.
    # Phantom дохода не создаётся, потому что Дебет-сторона — перевод
    # (affects_analytics=False). Здесь фиксируем сам расход пользователя.
    (_BankRule(
        skeleton_keywords=(
            "погашение процентов",
            "проценты пользование",
            "проценты договору",
            "уплата процентов",
        ),
        direction="income",
        account_type_filter=("loan", "credit_card", "installment_card"),
        operation_type="regular",
        category_name="Проценты по кредитам",
        label="Яндекс Сплит: оплата процентов по договору",
    ), 0.18),

    # ── Яндекс Сплит (credit/installment) — expense direction ───────────────
    # Credit/Split account: purchases via BNPL
    (_BankRule(
        skeleton_keywords=("оплата товаров", "оплата услуг"),
        direction="expense",
        account_type_filter=("loan", "credit_card", "installment_card"),
        operation_type="regular",
        category_name=None,
        label="Яндекс Сплит: покупка в кредит",
    ), 0.05),
    # Credit account: interest charge (bank debits the card for interest accrued)
    (_BankRule(
        skeleton_keywords=("погашение процентов", "проценты пользование", "проценты договору"),
        direction="expense",
        account_type_filter=("loan", "credit_card", "installment_card"),
        operation_type="regular",
        category_name="Проценты по кредитам",
        label="Яндекс: процентная часть платежа по кредиту",
    ), 0.15),
    # Credit account: principal repayment
    (_BankRule(
        skeleton_keywords=("погашение основного долга", "погашение просроченной", "погашение тела", "основного долга"),
        direction="expense",
        account_type_filter=("loan", "credit_card", "installment_card"),
        operation_type="transfer",
        category_name=None,
        label="Яндекс: погашение тела долга",
    ), 0.15),

    # ── Яндекс Дебет (regular) — expense direction ──────────────────────────
    # Debit account: outgoing payment to Яндекс Сплит by contract number.
    # suggest_target_by_contract=True → pipeline resolves target_account_id
    # from tokens.contract → the Сплит account with matching contract_number.
    (_BankRule(
        skeleton_keywords=("погашение", "оплата по договору", "перевод по договору"),
        direction="expense",
        account_type_filter=("main", "savings"),
        operation_type="transfer",
        category_name=None,
        label="Яндекс: платёж по кредитному договору → Сплит",
        suggest_target_by_contract=True,
    ), 0.12),

    # ── Cancellations / returns (any direction) ───────────────────────────────
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
        account_type_filter=("savings",),
        operation_type="regular",
        category_name="Проценты от вклада",
        label="Т-Банк: проценты по вкладу",
    ), 0.08),
    # Credit payment
    (_BankRule(
        skeleton_keywords=("погашение кредита", "ежемесячный платеж", "оплата по кредиту"),
        direction="expense",
        account_type_filter=("main",),
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
        account_type_filter=("savings",),
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
        identifier_key: str | None = None,
        identifier_value: str | None = None,
    ) -> BankMechanicsResult:
        """Match bank rules and check cross-session risk.

        identifier_key / identifier_value — the strongest token extracted from
        the row (contract / phone / iban / card). Used to resolve
        target_account_id when a rule fires with suggest_target_by_contract=True.
        """
        if not bank_code or not account:
            return BankMechanicsResult()

        rules = BANK_RULES.get(bank_code, [])
        account_type = str(getattr(account, "account_type", "") or "")

        matched_rule: _BankRule | None = None
        matched_boost: float = 0.0
        for rule, boost in rules:
            if rule.matches(skeleton, direction, account_type):
                matched_rule = rule
                matched_boost = boost
                break  # first matching rule wins

        suggest_exclude = False
        resolved_target: int | None = None

        if matched_rule is not None:
            suggest_exclude = matched_rule.suggest_exclude
            # P-02: resolve target_account_id by contract token so Дебет
            # transfer rows can be automatically paired with the correct Сплит
            # account without requiring the user to pick it manually.
            if (
                matched_rule.suggest_target_by_contract
                and identifier_key == "contract"
                and identifier_value
            ):
                target = self._account_repo.find_by_contract_number(
                    user_id=session.user_id,
                    contract_number=identifier_value,
                )
                if target is not None and target.id != account.id:
                    resolved_target = target.id

        result_op = matched_rule.operation_type if matched_rule else None
        result_cat = matched_rule.category_name if matched_rule else None
        result_label = matched_rule.label if matched_rule else None

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
        return BankMechanicsResult(
            operation_type=result_op,
            category_name=result_cat,
            label=result_label,
            confidence_boost=matched_boost,
            cross_session_warning=warning,
            suggest_exclude=suggest_exclude,
            resolved_target_account_id=resolved_target,
        )

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

        if is_credit or account_type in ("loan", "credit_card", "installment_card"):
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
