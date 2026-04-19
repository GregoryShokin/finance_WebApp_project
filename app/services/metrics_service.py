"""
Metrics service — трёхслойный Поток, Капитал, DTI, Буфер устойчивости, FI-score.

Decision 2026-04-19: Фаза 2 — новые формулы метрик.
Ref: financeapp-vault/01-Metrics/Поток.md
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction


# ── Helpers ───────────────────────────────────────────────────────────────────

def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _month_start_dt(d: date) -> datetime:
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc)


def _month_end_dt(d: date) -> datetime:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return datetime(d.year, d.month, last_day, 23, 59, 59, tzinfo=timezone.utc)


def _prev_month(d: date, n: int) -> date:
    """Return the 1st day of the month that is n months before d."""
    total_months = d.year * 12 + (d.month - 1) - n
    year, month = divmod(total_months, 12)
    return date(year, month + 1, 1)


def _aware(dt):
    """Return tz-aware datetime (assume UTC for naive)."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Constants
AVG_WINDOW_MONTHS = 12  # Phase 2: unified averaging window (was 3)
INTEREST_CATEGORY_NAME = "Проценты по кредитам"
LIQUID_ACCOUNT_TYPES = {"regular", "cash", "deposit"}
CREDIT_CARD_TYPES = {"credit_card", "installment_card"}
ALL_CREDIT_TYPES = {"credit", "credit_card", "installment_card"}


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FIScoreBreakdown:
    """Normalised FI-score components (0..10 each) + weighted total.

    Single source of truth for FI-score v1.4.
    Weights: savings 0.20 + capital 0.30 + dti 0.25 + buffer 0.25 = 1.00
    """
    savings_score: float
    capital_score: float
    dti_score: float
    buffer_score: float
    total: float


@dataclass
class FinancialIndependenceMetric:
    percent: float
    passive_income: Decimal
    avg_expenses: Decimal
    gap: Decimal
    months_of_data: int


@dataclass
class SavingsRateMetric:
    percent: float
    invested: Decimal
    total_income: Decimal


# ── Service ───────────────────────────────────────────────────────────────────

class MetricsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── 1. Financial independence ─────────────────────────────────────────────

    def get_financial_independence(
        self, user_id: int, current_month: date
    ) -> FinancialIndependenceMetric | None:
        """
        FI = passive_income_this_month / avg_expenses_last_12_months × 100.

        Phase 2: window extended from 3 → 12 months.
        """
        passive_cat_ids: set[int] = {
            c.id for c in self.db.query(Category).filter(
                Category.user_id == user_id,
                Category.kind == "income",
                Category.priority == "income_passive",
            ).all()
        }
        regular_expense_cat_ids: set[int] = {
            c.id for c in self.db.query(Category).filter(
                Category.user_id == user_id,
                Category.kind == "expense",
                Category.priority.in_(["expense_essential", "expense_secondary"]),
            ).all()
        }

        date_from = _month_start_dt(current_month)
        date_to = _month_end_dt(current_month)

        income_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "income",
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .all()
        )

        passive_income = sum(
            (Decimal(str(tx.amount)) for tx in income_txns if tx.category_id in passive_cat_ids),
            Decimal("0"),
        )

        # Last 12 completed months — expenses per month
        monthly_expenses: list[Decimal] = []
        for n in range(1, AVG_WINDOW_MONTHS + 1):
            prev = _prev_month(current_month, n)
            expense_txns = (
                self.db.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.type == "expense",
                    Transaction.affects_analytics.is_(True),
                    Transaction.transaction_date >= _month_start_dt(prev),
                    Transaction.transaction_date <= _month_end_dt(prev),
                )
                .all()
            )
            month_total = sum(
                (Decimal(str(tx.amount)) for tx in expense_txns if tx.category_id in regular_expense_cat_ids),
                Decimal("0"),
            )
            monthly_expenses.append(month_total)

        months_of_data = sum(1 for m in monthly_expenses if m > 0)
        if months_of_data == 0:
            return None

        avg_expenses = _round2(
            sum(monthly_expenses, Decimal("0")) / Decimal(str(months_of_data))
        )

        if avg_expenses > 0:
            pct = float(passive_income / avg_expenses * 100)
        else:
            pct = 100.0 if passive_income > 0 else 0.0

        pct = min(pct, 999.0)
        gap = _round2(max(Decimal("0"), avg_expenses - passive_income))

        return FinancialIndependenceMetric(
            percent=round(pct, 2),
            passive_income=_round2(passive_income),
            avg_expenses=avg_expenses,
            gap=gap,
            months_of_data=months_of_data,
        )

    # ── 2. Savings rate ───────────────────────────────────────────────────────

    def get_savings_rate(
        self, user_id: int, current_month: date
    ) -> SavingsRateMetric:
        date_from = _month_start_dt(current_month)
        date_to = _month_end_dt(current_month)

        income_cat_ids: set[int] = {
            c.id for c in self.db.query(Category).filter(
                Category.user_id == user_id,
                Category.kind == "income",
                Category.priority.in_(["income_active", "income_passive"]),
            ).all()
        }

        income_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "income",
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .all()
        )
        total_income = sum(
            (Decimal(str(tx.amount)) for tx in income_txns if tx.category_id in income_cat_ids),
            Decimal("0"),
        )

        invest_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.affects_analytics.is_(True),
                Transaction.operation_type == "investment_buy",
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .all()
        )
        invested = sum(
            (Decimal(str(tx.amount)) for tx in invest_txns),
            Decimal("0"),
        )

        pct = float(invested / total_income * 100) if total_income > 0 else 0.0

        return SavingsRateMetric(
            percent=round(pct, 2),
            invested=_round2(invested),
            total_income=_round2(total_income),
        )

    # ── 3. Account-type caches ────────────────────────────────────────────────

    def _get_accounts_by_type(self, user_id: int) -> dict[str, list[Account]]:
        """Fetch active accounts once, bucket by type category."""
        accounts = (
            self.db.query(Account)
            .filter(Account.user_id == user_id, Account.is_active.is_(True))
            .all()
        )
        liquid: list[Account] = []
        credit: list[Account] = []
        credit_card: list[Account] = []
        deposit: list[Account] = []
        for acc in accounts:
            if acc.account_type in LIQUID_ACCOUNT_TYPES:
                liquid.append(acc)
            if acc.account_type == "deposit":
                deposit.append(acc)
            if acc.account_type in ALL_CREDIT_TYPES:
                credit.append(acc)
            if acc.account_type in CREDIT_CARD_TYPES:
                credit_card.append(acc)
        return {
            "all": accounts,
            "liquid": liquid,
            "credit": credit,
            "credit_card": credit_card,
            "deposit": deposit,
        }

    # ── 4. Flow helpers ───────────────────────────────────────────────────────

    def _get_month_transactions(self, user_id: int, month: date) -> list[Transaction]:
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= _month_start_dt(month),
                Transaction.transaction_date <= _month_end_dt(month),
            )
            .all()
        )

    def _get_month_transactions_all(self, user_id: int, month: date) -> list[Transaction]:
        """All transactions in month (including transfers, affects_analytics=False).

        Needed for Full Flow (balance delta) and CC compensator.
        """
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= _month_start_dt(month),
                Transaction.transaction_date <= _month_end_dt(month),
            )
            .all()
        )

    def _calc_basic_flow_for_month(self, txns: list[Transaction]) -> Decimal:
        regular_income = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "income" and tx.is_regular
             and tx.operation_type not in ("transfer", "credit_disbursement", "credit_early_repayment")),
            Decimal("0"),
        )
        regular_expense = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "expense" and tx.is_regular
             and tx.operation_type not in ("transfer", "credit_early_repayment")),
            Decimal("0"),
        )
        return _round2(regular_income - regular_expense)

    def _calc_regular_income_for_month(self, txns: list[Transaction]) -> Decimal:
        return sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "income" and tx.is_regular
             and tx.operation_type not in ("transfer", "credit_disbursement", "credit_early_repayment")),
            Decimal("0"),
        )

    def _calc_full_flow_for_month(
        self,
        txns: list[Transaction],
        liquid_account_ids: set[int],
        credit_account_ids: set[int],
    ) -> Decimal:
        """
        Полный поток = Δ ликвидного кэша за период.

        Что ПРИШЛО в ликвидную сферу:
          + Σ(income, account_id in LIQUID) — зарплата, бонусы, disbursement наличными
        Что УШЛО:
          − Σ(expense, account_id in LIQUID) — все расходы с ликвидных счетов
          − Σ(transfer, account_id in LIQUID, target_account_id in CREDIT) — платежи по кредитам тело
          − Σ(credit_early_repayment, account_id in LIQUID) — досрочные с ликвидных

        Переводы ликвидный→ликвидный (regular↔deposit) нетто = 0, не включаем.
        Покупки на КК идут со счёта КК (не с LIQUID) → не вычитаются.

        Ref: financeapp-vault/01-Metrics/Поток.md §2.1.3
        """
        total = Decimal("0")

        for tx in txns:
            amount = Decimal(str(tx.amount))
            acc_id = tx.account_id
            target_id = tx.target_account_id
            op = tx.operation_type
            ttype = tx.type

            # Skip transfers that are liquid→liquid (no net change)
            if op == "transfer":
                if acc_id in liquid_account_ids and target_id in liquid_account_ids:
                    continue
                # transfer liquid→credit (body of credit payment): outflow
                if acc_id in liquid_account_ids and target_id in credit_account_ids:
                    total -= amount
                # transfer liquid→external (unlikely) or credit→liquid (refund): ignore for now
                continue

            if op == "credit_early_repayment":
                if acc_id in liquid_account_ids:
                    total -= amount
                continue

            # Regular income / expense — only count if hitting a liquid account
            if acc_id not in liquid_account_ids:
                continue

            if ttype == "income":
                # Include credit_disbursement when it lands on a liquid account
                # (physically cash arrived, debt tracked separately).
                total += amount
            elif ttype == "expense":
                total -= amount

        return _round2(total)

    def calculate_flow(self, user_id: int, year: int, month: int) -> dict:
        """
        Трёхслойный Поток: Базовый, Свободные средства, Полный (с компенсатором).
        """
        current = date(year, month, 1)
        txns = self._get_month_transactions(user_id, current)
        txns_all = self._get_month_transactions_all(user_id, current)

        accounts = self._get_accounts_by_type(user_id)
        liquid_ids = {a.id for a in accounts["liquid"]}
        credit_ids = {a.id for a in accounts["credit"]}
        cc_ids = {a.id for a in accounts["credit_card"]}

        basic_flow = self._calc_basic_flow_for_month(txns)
        full_flow = self._calc_full_flow_for_month(txns_all, liquid_ids, credit_ids)

        # Free capital (свободные средства) = basic_flow − Σ(тело обязательных платежей)
        avg_interest_by_account = self._calc_avg_interest_per_account(
            user_id, {a.id for a in accounts["credit"]}, months=3
        )
        credit_body_payments = self._calc_credit_body_payments(
            accounts["credit"], avg_interest_by_account
        )
        free_capital = _round2(basic_flow - credit_body_payments)

        # CC debt compensator = прирост долга по кредиткам за период
        cc_debt_compensator = self._calc_cc_debt_compensator_from_txns(txns_all, cc_ids)

        # lifestyle_indicator: avg basic_flow / avg regular_income over last 12 completed months
        basic_flows: list[Decimal] = []
        regular_incomes: list[Decimal] = []
        for n in range(1, AVG_WINDOW_MONTHS + 1):
            prev = _prev_month(current, n)
            prev_txns = self._get_month_transactions(user_id, prev)
            if prev_txns:
                basic_flows.append(self._calc_basic_flow_for_month(prev_txns))
                regular_incomes.append(self._calc_regular_income_for_month(prev_txns))

        lifestyle_indicator = None
        if regular_incomes:
            avg_basic = sum(basic_flows, Decimal("0")) / Decimal(str(len(basic_flows)))
            avg_income = sum(regular_incomes, Decimal("0")) / Decimal(str(len(regular_incomes)))
            if avg_income > 0:
                lifestyle_indicator = round(float(avg_basic / avg_income * 100), 2)

        if lifestyle_indicator is not None:
            if lifestyle_indicator >= 20:
                zone = "healthy"
            elif lifestyle_indicator >= 0:
                zone = "tight"
            else:
                zone = "deficit"
        else:
            zone = "tight"

        # Trend: basic_flow this month vs previous month
        trend = None
        prev_month_date = _prev_month(current, 1)
        prev_txns = self._get_month_transactions(user_id, prev_month_date)
        if prev_txns:
            prev_basic = self._calc_basic_flow_for_month(prev_txns)
            trend = _round2(basic_flow - prev_basic)

        return {
            "basic_flow": basic_flow,
            "free_capital": free_capital,
            "full_flow": full_flow,
            "cc_debt_compensator": cc_debt_compensator,
            "credit_body_payments": _round2(credit_body_payments),
            "lifestyle_indicator": lifestyle_indicator,
            "zone": zone,
            "trend": trend,
        }

    # ── 4a. Free capital helpers (GAP #4) ─────────────────────────────────────

    def _calc_avg_interest_per_account(
        self, user_id: int, credit_account_ids: set[int], months: int = 3
    ) -> dict[int, Decimal]:
        """
        Среднемесячный расход процентов по кредиту за последние `months` мес.

        Берёт expense-транзакции с credit_account_id, operation_type=regular,
        категория «Проценты по кредитам».
        """
        if not credit_account_ids:
            return {}

        today = date.today()
        current = date(today.year, today.month, 1)
        window_start = _month_start_dt(_prev_month(current, months))
        window_end = _month_end_dt(_prev_month(current, 1))

        # Find the interest category id
        interest_cat = (
            self.db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.is_system.is_(True),
                Category.name == INTEREST_CATEGORY_NAME,
            )
            .first()
        )
        interest_cat_id = interest_cat.id if interest_cat else None

        q = self.db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.operation_type == "regular",
            Transaction.credit_account_id.in_(credit_account_ids),
            Transaction.transaction_date >= window_start,
            Transaction.transaction_date <= window_end,
        )
        if interest_cat_id is not None:
            q = q.filter(Transaction.category_id == interest_cat_id)

        per_account_total: dict[int, Decimal] = {}
        month_seen: dict[int, set[str]] = {}
        for tx in q.all():
            aid = tx.credit_account_id
            if aid is None:
                continue
            amt = Decimal(str(tx.amount))
            per_account_total[aid] = per_account_total.get(aid, Decimal("0")) + amt
            key = tx.transaction_date.strftime("%Y-%m")
            month_seen.setdefault(aid, set()).add(key)

        result: dict[int, Decimal] = {}
        for aid, total in per_account_total.items():
            n = len(month_seen.get(aid, set())) or 1
            result[aid] = _round2(total / Decimal(str(n)))
        return result

    def _calc_credit_body_payments(
        self,
        credit_accounts: list[Account],
        avg_interest_by_account: dict[int, Decimal],
    ) -> Decimal:
        """
        Σ(тело обязательных платежей по всем кредитам) за месяц.

        Body calculation by account type:
        - installment_card: body = monthly_payment (0% rassrochka, проценты = 0)
        - credit_card: body = monthly_payment (минимальный платёж ≈ тело)
        - credit/mortgage: body = monthly_payment − avg_interest_expense;
          если нет данных по процентам → 0.8 × monthly_payment
        """
        total_body = Decimal("0")
        for acc in credit_accounts:
            mp = getattr(acc, "monthly_payment", None)
            if mp is None:
                continue
            mp_dec = Decimal(str(mp))
            if mp_dec <= 0:
                continue

            acct_type = acc.account_type
            if acct_type == "installment_card":
                body = mp_dec
            elif acct_type == "credit_card":
                body = mp_dec
            else:  # credit (включая mortgage)
                avg_int = avg_interest_by_account.get(acc.id)
                if avg_int is not None and avg_int > 0:
                    body = max(mp_dec - avg_int, Decimal("0"))
                else:
                    body = mp_dec * Decimal("0.8")

            total_body += body

        return total_body

    def calculate_free_capital(self, user_id: int, year: int, month: int) -> dict:
        """
        Свободные средства = basic_flow − Σ(тело обязательных платежей).

        Ref: financeapp-vault/01-Metrics/Поток.md §2.1.2 (GAP #4)
        """
        current = date(year, month, 1)
        txns = self._get_month_transactions(user_id, current)
        basic_flow = self._calc_basic_flow_for_month(txns)

        accounts = self._get_accounts_by_type(user_id)
        avg_interest_by_account = self._calc_avg_interest_per_account(
            user_id, {a.id for a in accounts["credit"]}, months=3
        )
        body = self._calc_credit_body_payments(accounts["credit"], avg_interest_by_account)
        return {
            "free_capital": _round2(basic_flow - body),
            "credit_body_payments": _round2(body),
        }

    # ── 4b. CC debt compensator ───────────────────────────────────────────────

    def _calc_cc_debt_compensator_from_txns(
        self,
        txns: list[Transaction],
        cc_account_ids: set[int],
    ) -> Decimal:
        """
        Компенсатор для декомпозиции Полного потока = сумма покупок с КК за период.

        Назначение: объясняет расхождение между "записано как расход" и "ушло с ликвидных счетов".
        Покупка на КК (account_id = credit_card) записана как expense, но ликвидный баланс
        пользователя не уменьшился — изменился только долг на кредитке.

        Погашение КК (transfer к кредитному счёту) НЕ входит в компенсатор — оно уже отражено
        в строке "Тело кредитных платежей" (credit_body_payments) декомпозиции.

        Формула: compensator = Σ(amount  где  account_id ∈ {credit_card, installment_card}  и  type='expense')

        Свойства:
          - Всегда ≥ 0 (покупки не могут быть отрицательными)
          - Ноль, если пользователь не делал покупок на КК в периоде
          - Максимально равен сумме всех покупок на КК

        Ref: financeapp-vault/01-Metrics/Поток.md, решение 2026-04-19.
        """
        if not cc_account_ids:
            return Decimal("0")

        total = Decimal("0")
        for tx in txns:
            if tx.type == "expense" and tx.account_id in cc_account_ids:
                total += Decimal(str(tx.amount))
        return _round2(total)

    def calculate_cc_debt_compensator(self, user_id: int, year: int, month: int) -> Decimal:
        """Public wrapper: прирост долга по кредиткам за месяц."""
        current = date(year, month, 1)
        txns_all = self._get_month_transactions_all(user_id, current)
        accounts = self._get_accounts_by_type(user_id)
        cc_ids = {a.id for a in accounts["credit_card"]}
        return self._calc_cc_debt_compensator_from_txns(txns_all, cc_ids)

    # ── 5. Capital metric ────────────────────────────────────────────────────

    def calculate_capital(self, user_id: int) -> dict:
        from app.services.capital_snapshot_service import CapitalSnapshotService

        accounts = (
            self.db.query(Account)
            .filter(Account.user_id == user_id, Account.is_active.is_(True))
            .all()
        )

        liquid_assets = Decimal("0")
        deposits = Decimal("0")
        credit_debt = Decimal("0")

        for acc in accounts:
            if acc.account_type in ("regular", "cash"):
                liquid_assets += Decimal(str(acc.balance))
            elif acc.account_type == "deposit":
                deposits += Decimal(str(acc.balance))
            elif acc.account_type in ("credit", "credit_card", "installment_card"):
                if acc.credit_current_amount is not None:
                    credit_debt += Decimal(str(acc.credit_current_amount))
                elif acc.account_type == "credit_card" and acc.balance < 0:
                    credit_debt += abs(Decimal(str(acc.balance)))

        capital = _round2(liquid_assets + deposits - credit_debt)

        snap_svc = CapitalSnapshotService(self.db)
        trend_data = snap_svc.get_trend(user_id)

        return {
            "capital": capital,
            "trend": trend_data["trend_3m"],
            "trend_3m": trend_data["trend_3m"],
            "trend_6m": trend_data["trend_6m"],
            "trend_12m": trend_data["trend_12m"],
            "snapshots_count": trend_data["snapshots_count"],
        }

    # ── 6. DTI metric ────────────────────────────────────────────────────────

    def calculate_dti(self, user_id: int) -> dict:
        today = date.today()
        current = date(today.year, today.month, 1)
        prev_month = _prev_month(current, 1)

        credit_accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.is_active.is_(True),
                Account.account_type.in_(tuple(ALL_CREDIT_TYPES)),
            )
            .all()
        )
        credit_account_ids = {acc.id for acc in credit_accounts}

        # DTI numerator: interest (expense/regular with credit_account_id) +
        # body (transfer with target_account_id in credit accounts).
        # Ref: financeapp-vault/14-Specifications §2.2, Phase 3 Block Б (2026-04-19).
        interest_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.operation_type == "regular",
                Transaction.credit_account_id.isnot(None),
            )
            .all()
        )
        # Body transactions: transfer to credit account WITH credit_account_id set.
        # credit_account_id IS NOT NULL distinguishes a real loan body payment from a
        # regular top-up of a credit card (which has credit_account_id=NULL).
        body_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.operation_type == "transfer",
                Transaction.target_account_id.in_(list(credit_account_ids)),
                Transaction.credit_account_id.isnot(None),
            )
            .all()
        )
        all_credit_txns = interest_txns + body_txns

        # Payments in previous completed month
        prev_month_start = _month_start_dt(prev_month)
        prev_month_end = _month_end_dt(prev_month)
        prev_month_payment_by_account: dict[int, Decimal] = {}
        for tx in all_credit_txns:
            if tx.operation_type == "transfer":
                account_id = tx.target_account_id
            else:
                account_id = tx.credit_account_id
            if account_id is None or account_id not in credit_account_ids:
                continue
            tx_dt = _aware(tx.transaction_date)
            if prev_month_start <= tx_dt <= prev_month_end:
                prev_month_payment_by_account[account_id] = (
                    prev_month_payment_by_account.get(account_id, Decimal("0"))
                    + Decimal(str(tx.amount))
                )

        # Fallback: most recent payment per account
        last_payment_by_account: dict[int, Decimal] = {}
        last_payment_date_by_account: dict[int, object] = {}
        for tx in all_credit_txns:
            if tx.operation_type == "transfer":
                account_id = tx.target_account_id
            else:
                account_id = tx.credit_account_id
            if account_id is None or account_id not in credit_account_ids:
                continue
            tx_date = tx.transaction_date
            existing_date = last_payment_date_by_account.get(account_id)
            if existing_date is None or tx_date > existing_date:
                last_payment_by_account[account_id] = Decimal(str(tx.amount))
                last_payment_date_by_account[account_id] = tx_date

        monthly_payments = Decimal("0")
        for acc in credit_accounts:
            payment = prev_month_payment_by_account.get(acc.id)
            if payment is None or payment == 0:
                payment = last_payment_by_account.get(acc.id)
            if payment is None or payment == 0:
                fallback = getattr(acc, "monthly_payment", None)
                if fallback is not None:
                    payment = Decimal(str(fallback))
            if payment and payment > 0:
                monthly_payments += payment

        # Denominator: avg regular income over last 12 completed months
        regular_incomes: list[Decimal] = []
        all_incomes: list[Decimal] = []
        for n in range(1, AVG_WINDOW_MONTHS + 1):
            prev = _prev_month(current, n)
            prev_txns = self._get_month_transactions(user_id, prev)
            ri = self._calc_regular_income_for_month(prev_txns)
            regular_incomes.append(ri)
            ai = sum(
                (Decimal(str(tx.amount)) for tx in prev_txns
                 if tx.type == "income"
                 and tx.operation_type not in ("transfer", "credit_disbursement", "credit_early_repayment")),
                Decimal("0"),
            )
            all_incomes.append(ai)

        total_income = sum(regular_incomes, Decimal("0"))
        months_with_data = sum(1 for r in regular_incomes if r > 0)
        avg_regular_income = (
            _round2(total_income / Decimal(str(months_with_data)))
            if months_with_data > 0 else Decimal("0")
        )

        if avg_regular_income == 0:
            total_all = sum(all_incomes, Decimal("0"))
            months_all = sum(1 for a in all_incomes if a > 0)
            if months_all > 0:
                avg_regular_income = _round2(total_all / Decimal(str(months_all)))

        dti_percent = None
        zone = None
        if avg_regular_income > 0:
            dti_percent = round(float(monthly_payments / avg_regular_income * 100), 2)
            if dti_percent < 30:
                zone = "normal"
            elif dti_percent < 40:
                zone = "acceptable"
            elif dti_percent < 60:
                zone = "danger"
            else:
                zone = "critical"

        return {
            "dti_percent": dti_percent,
            "zone": zone,
            "monthly_payments": _round2(monthly_payments),
            "regular_income": avg_regular_income,
        }

    # ── 7. Reserve (legacy — kept for health-service compat) ──────────────────

    def calculate_reserve(self, user_id: int) -> dict:
        accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.is_active.is_(True),
                Account.account_type.in_(("regular", "cash")),
            )
            .all()
        )
        available_cash = _round2(sum(
            (Decimal(str(acc.balance)) for acc in accounts if acc.balance > 0),
            Decimal("0"),
        ))

        today = date.today()
        current = date(today.year, today.month, 1)

        monthly_outflows: list[Decimal] = []
        for n in range(1, 7):
            prev = _prev_month(current, n)
            prev_txns = self._get_month_transactions(user_id, prev)
            if not prev_txns:
                continue
            outflow = sum(
                (Decimal(str(tx.amount)) for tx in prev_txns
                 if tx.type == "expense"
                 and tx.operation_type not in ("transfer", "credit_early_repayment")),
                Decimal("0"),
            )
            monthly_outflows.append(outflow)

        if len(monthly_outflows) >= 6:
            used = monthly_outflows[:6]
        else:
            used = monthly_outflows[:3] if len(monthly_outflows) >= 3 else monthly_outflows

        avg_outflow = Decimal("0")
        if used:
            avg_outflow = _round2(sum(used, Decimal("0")) / Decimal(str(len(used))))

        months = None
        zone = None
        if avg_outflow > 0:
            months = round(float(available_cash / avg_outflow), 1)
            if months < 1:
                zone = "critical"
            elif months < 3:
                zone = "minimum"
            elif months <= 6:
                zone = "normal"
            else:
                zone = "excellent"

        return {
            "months": months,
            "zone": zone,
            "available_cash": available_cash,
            "monthly_outflow": avg_outflow,
        }

    # ── 8. Buffer stability (v1.4 replaces reserve in FI-score) ───────────────

    def calculate_buffer_stability(self, user_id: int) -> dict:
        """
        Буфер устойчивости = Σ(deposit account balances) / avg(monthly_expenses, 12 мес)

        Ref: financeapp-vault/01-Metrics/Буфер устойчивости.md
        Zones: <1 → critical, 1–3 → minimum, 3–6 → normal, >6 → excellent.
        """
        accounts = self._get_accounts_by_type(user_id)
        deposit_balance = _round2(sum(
            (Decimal(str(acc.balance)) for acc in accounts["deposit"] if acc.balance is not None),
            Decimal("0"),
        ))

        # avg expenses over last 12 completed months
        today = date.today()
        current = date(today.year, today.month, 1)
        monthly_outflows: list[Decimal] = []
        for n in range(1, AVG_WINDOW_MONTHS + 1):
            prev = _prev_month(current, n)
            prev_txns = self._get_month_transactions(user_id, prev)
            if not prev_txns:
                continue
            outflow = sum(
                (Decimal(str(tx.amount)) for tx in prev_txns
                 if tx.type == "expense"
                 and tx.operation_type not in ("transfer", "credit_early_repayment")),
                Decimal("0"),
            )
            if outflow > 0:
                monthly_outflows.append(outflow)

        avg_monthly_expense = Decimal("0")
        if monthly_outflows:
            avg_monthly_expense = _round2(
                sum(monthly_outflows, Decimal("0")) / Decimal(str(len(monthly_outflows)))
            )

        months = None
        zone = None
        if avg_monthly_expense > 0 and deposit_balance > 0:
            months = round(float(deposit_balance / avg_monthly_expense), 1)
            if months < 1:
                zone = "critical"
            elif months < 3:
                zone = "minimum"
            elif months <= 6:
                zone = "normal"
            else:
                zone = "excellent"

        return {
            "months": months,
            "zone": zone,
            "deposit_balance": deposit_balance,
            "avg_monthly_expense": avg_monthly_expense,
        }

    # ── 9. FI-score v1.4 ─────────────────────────────────────────────────────

    def _build_fi_breakdown(
        self,
        flow: dict,
        capital: dict,
        dti: dict,
        buffer: dict,
    ) -> FIScoreBreakdown:
        """Pure function: compute normalised FI-score components.

        Single source of truth (v1.4). Called by both _calc_fi_score
        and calculate_fi_score_breakdown.
        """
        # Savings score: lifestyle_indicator (0%→0, ≥30%→10)
        li = flow.get("lifestyle_indicator")
        if li is not None:
            savings_score = min(max(li / 30 * 10, 0), 10)
        else:
            savings_score = 5.0

        # Capital trajectory: trend_3m / |capital| normalised → clamp(5 + rel*5, 0,10)
        trend_3m = capital.get("trend_3m")
        snapshots_count = capital.get("snapshots_count", 0)
        if trend_3m is not None and snapshots_count >= 3:
            cap_value = float(capital.get("capital", 1) or 1)
            relative = float(trend_3m) / max(abs(cap_value), 1)
            relative = max(min(relative, 1.0), -1.0)
            capital_score = max(min(5.0 + relative * 5.0, 10.0), 0.0)
        else:
            capital_score = 5.0

        # DTI inverse: 0%→10, ≥60%→0
        dti_pct = dti.get("dti_percent")
        if dti_pct is not None:
            dti_score = max(10 - (dti_pct / 6), 0)
        else:
            dti_score = 10.0

        # Buffer stability: 0 мес→0, ≥6 мес→10
        months = buffer.get("months")
        if months is not None:
            buffer_score = min(months / 6 * 10, 10)
        else:
            buffer_score = 0.0

        total = round(
            savings_score * 0.20
            + capital_score * 0.30
            + dti_score * 0.25
            + buffer_score * 0.25,
            1,
        )
        return FIScoreBreakdown(
            savings_score=round(savings_score, 2),
            capital_score=round(capital_score, 2),
            dti_score=round(dti_score, 2),
            buffer_score=round(buffer_score, 2),
            total=total,
        )

    def _calc_fi_score(self, flow: dict, capital: dict, dti: dict, buffer: dict) -> float:
        """FI-score v1.4 total (delegates to _build_fi_breakdown)."""
        return self._build_fi_breakdown(flow, capital, dti, buffer).total

    def calculate_fi_score_breakdown(self, user_id: int) -> FIScoreBreakdown:
        """Public method: compute FI-score breakdown from current metrics.

        Used by FinancialHealthService to unify FI-score across endpoints.
        """
        summary = self.calculate_metrics_summary(user_id)
        return self._build_fi_breakdown(
            flow=summary["flow"],
            capital=summary["capital"],
            dti=summary["dti"],
            buffer=summary["buffer_stability"],
        )

    # ── 10. Recommendations ──────────────────────────────────────────────────

    ZONE_PRIORITY = {
        "critical": 0,
        "deficit": 1,
        "danger": 1,
        "minimum": 2,
        "tight": 2,
        "acceptable": 3,
        "normal": 4,
        "healthy": 5,
        "green": 5,
        "excellent": 6,
    }

    METRIC_TIEBREAK = {"buffer_stability": 0, "reserve": 0, "dti": 1, "flow": 2, "capital": 3}

    RECOMMENDATIONS = {
        ("flow", "deficit"): {
            "message_key": "flow_deficit",
            "title": "Расходы превышают доход",
            "message": "Регулярные расходы и платежи по кредитам больше стабильного дохода. "
                       "Проверь топ-3 категории расходов и рассмотри рефинансирование, если нагрузка > 30%.",
        },
        ("flow", "tight"): {
            "message_key": "flow_tight",
            "title": "Тонкая подушка",
            "message": "Одна непредвиденная трата может увести в минус. Ищи, что можно оптимизировать.",
        },
        ("dti", "danger"): {
            "message_key": "dti_danger",
            "title": "Высокая кредитная нагрузка",
            "message": "Более 40% дохода уходит на кредиты. Рассмотри рефинансирование или досрочное погашение.",
        },
        ("dti", "critical"): {
            "message_key": "dti_critical",
            "title": "Критическая нагрузка",
            "message": "Более 60% дохода на кредиты — зона риска. Рефинансирование или реструктуризация могут помочь.",
        },
        ("buffer_stability", "critical"): {
            "message_key": "buffer_critical",
            "title": "Нет подушки безопасности",
            "message": "На вкладах меньше месяца расходов. Цель Этажа 2: 3 месяца на депозитах.",
        },
        ("buffer_stability", "minimum"): {
            "message_key": "buffer_minimum",
            "title": "Буфер растёт",
            "message": "1–3 месяца на вкладах — хороший старт. Цель: 3–6 месяцев расходов.",
        },
        ("reserve", "minimum"): {
            "message_key": "reserve_minimum",
            "title": "Запас растёт",
            "message": "Запас 1–3 месяца — хороший старт. Цель: 3–6 месяцев расходов.",
        },
    }

    def _get_fi_zone(self, fi_score: float) -> str:
        if fi_score < 3:
            return "risk"
        elif fi_score < 6:
            return "growth"
        elif fi_score < 8:
            return "path"
        else:
            return "freedom"

    def _build_recommendations(self, flow: dict, capital: dict, dti: dict, buffer: dict) -> tuple[str, list[dict]]:
        metric_zones = {
            "flow": flow.get("zone", "healthy"),
            "capital": "green" if capital.get("trend") is None or capital.get("trend", 0) >= 0 else "red",
            "dti": dti.get("zone") or "normal",
            "buffer_stability": buffer.get("zone") or "normal",
        }

        if capital.get("trend") is not None and capital["trend"] < 0:
            metric_zones["capital"] = "danger"

        sorted_metrics = sorted(
            metric_zones.items(),
            key=lambda x: (self.ZONE_PRIORITY.get(x[1], 5), self.METRIC_TIEBREAK.get(x[0], 3)),
        )
        weakest_metric = sorted_metrics[0][0]

        recs: list[dict] = []
        for metric, zone in sorted_metrics:
            zone_priority = self.ZONE_PRIORITY.get(zone, 5)
            if zone_priority >= 4:
                continue

            key = (metric, zone)
            if key in self.RECOMMENDATIONS:
                rec = self.RECOMMENDATIONS[key]
                recs.append({
                    "metric": metric,
                    "zone": zone,
                    "priority": len(recs) + 1,
                    "message_key": rec["message_key"],
                    "title": rec["title"],
                    "message": rec["message"],
                })

            if metric == "capital" and capital.get("trend") is not None and capital["trend"] < 0:
                recs.append({
                    "metric": "capital",
                    "zone": "declining",
                    "priority": len(recs) + 1,
                    "message_key": "capital_declining",
                    "title": "Капитал уменьшается",
                    "message": "Капитал падает. Проверь, растут ли долги быстрее накоплений.",
                })

            if len(recs) >= 3:
                break

        return weakest_metric, recs

    # ── 11. Summary ──────────────────────────────────────────────────────────

    def calculate_metrics_summary(self, user_id: int) -> dict:
        """Phase 2: includes free_capital, cc_debt_compensator, buffer_stability."""
        today = date.today()
        flow = self.calculate_flow(user_id, today.year, today.month)
        capital = self.calculate_capital(user_id)
        dti = self.calculate_dti(user_id)
        buffer = self.calculate_buffer_stability(user_id)
        reserve = self.calculate_reserve(user_id)  # legacy compat
        fi_score = self._calc_fi_score(flow, capital, dti, buffer)

        return {
            "flow": flow,
            "capital": capital,
            "dti": dti,
            "buffer_stability": buffer,
            "reserve": reserve,
            "fi_score": fi_score,
        }

    def calculate_health_summary(self, user_id: int) -> dict:
        summary = self.calculate_metrics_summary(user_id)
        fi_score = summary["fi_score"]
        fi_zone = self._get_fi_zone(fi_score)
        weakest_metric, recommendations = self._build_recommendations(
            summary["flow"], summary["capital"], summary["dti"], summary["buffer_stability"]
        )
        return {
            "metrics": summary,
            "fi_score": fi_score,
            "fi_zone": fi_zone,
            "weakest_metric": weakest_metric,
            "recommendations": recommendations,
        }
