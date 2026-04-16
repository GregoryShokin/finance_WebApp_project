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


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FinancialIndependenceMetric:
    percent: float           # passive_income / avg_expenses × 100, capped at 999
    passive_income: Decimal  # пассивный доход текущего месяца
    avg_expenses: Decimal    # среднее расходов за последние 3 месяца
    gap: Decimal             # сколько не хватает пассивного дохода до 100 %
    months_of_data: int      # сколько из 3 месяцев содержат данные по расходам


@dataclass
class SavingsRateMetric:
    percent: float          # invested / total_income × 100
    invested: Decimal       # сумма инвестиций за месяц
    total_income: Decimal   # суммарный доход (активный + пассивный) за месяц


# ── Service ───────────────────────────────────────────────────────────────────

class MetricsService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._ic_account_ids: set[int] | None = None

    def _get_installment_card_ids(self, user_id: int) -> set[int]:
        """Cache installment_card account IDs per service instance."""
        if self._ic_account_ids is None:
            rows = (
                self.db.query(Account.id)
                .filter(Account.user_id == user_id, Account.account_type == "installment_card")
                .all()
            )
            self._ic_account_ids = {r.id for r in rows}
        return self._ic_account_ids

    def _is_real_expense(self, tx: Transaction, user_id: int) -> bool:
        """Check if a transaction is a real expense (not an installment-card purchase)."""
        ic_ids = self._get_installment_card_ids(user_id)
        return tx.account_id not in ic_ids

    # ── 1. Financial independence ─────────────────────────────────────────────

    def get_financial_independence(
        self, user_id: int, current_month: date
    ) -> FinancialIndependenceMetric | None:
        """
        Financial independence = passive_income_this_month / avg_expenses_last_3_months × 100.

        passive_income: transactions in income categories with priority='income_passive'
        avg_expenses:   average of monthly totals for expense categories with
                        priority in ('expense_essential', 'expense_secondary')
                        over the last 3 completed months (not current).

        Returns None when there are no expense data for any of the 3 reference months.
        """
        # Category ID sets
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

        # Current month passive income
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

        # Last 3 completed months — expenses per month
        monthly_expenses: list[Decimal] = []
        for n in range(1, 4):
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

        # Divide only by months that actually had expense data, not by 3
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
        """
        Savings rate = invested / total_income × 100.

        invested:     transactions with operation_type='investment_buy' in current month
        total_income: transactions in income categories (income_active + income_passive)
                      in current month
        """
        date_from = _month_start_dt(current_month)
        date_to = _month_end_dt(current_month)

        # Income category IDs (active + passive)
        income_cat_ids: set[int] = {
            c.id for c in self.db.query(Category).filter(
                Category.user_id == user_id,
                Category.kind == "income",
                Category.priority.in_(["income_active", "income_passive"]),
            ).all()
        }

        # Total income transactions
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

        # Investment purchases
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

    # ── 3. Flow metric ───────────────────────────────────────────────────────

    def _get_month_transactions(self, user_id: int, month: date) -> list[Transaction]:
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.affects_analytics.is_(True),
                Transaction.converted_to_installment.is_(False),
                Transaction.transaction_date >= _month_start_dt(month),
                Transaction.transaction_date <= _month_end_dt(month),
            )
            .all()
        )

    def _get_all_transactions(self, user_id: int) -> list[Transaction]:
        return (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.affects_analytics.is_(True),
                Transaction.converted_to_installment.is_(False),
            )
            .all()
        )

    def _calc_basic_flow_for_month(self, txns: list[Transaction], user_id: int) -> Decimal:
        regular_income = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "income" and tx.is_regular
             and tx.operation_type not in ("transfer", "credit_early_repayment")),
            Decimal("0"),
        )
        regular_expense = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "expense" and tx.is_regular
             and tx.operation_type not in ("transfer", "credit_payment", "credit_early_repayment")
             and self._is_real_expense(tx, user_id)),
            Decimal("0"),
        )
        credit_payments = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.operation_type == "credit_payment"),
            Decimal("0"),
        )
        return _round2(regular_income - regular_expense - credit_payments)

    def _calc_full_flow_for_month(self, txns: list[Transaction], user_id: int) -> Decimal:
        income = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "income"
             and tx.operation_type not in ("transfer", "credit_early_repayment")),
            Decimal("0"),
        )
        expense = sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "expense"
             and tx.operation_type not in ("transfer", "credit_early_repayment")
             and self._is_real_expense(tx, user_id)),
            Decimal("0"),
        )
        return _round2(income - expense)

    def _calc_regular_income_for_month(self, txns: list[Transaction]) -> Decimal:
        return sum(
            (Decimal(str(tx.amount)) for tx in txns
             if tx.type == "income" and tx.is_regular
             and tx.operation_type not in ("transfer", "credit_early_repayment")),
            Decimal("0"),
        )

    def calculate_flow(self, user_id: int, year: int, month: int) -> dict:
        current = date(year, month, 1)
        txns = self._get_month_transactions(user_id, current)

        basic_flow = self._calc_basic_flow_for_month(txns, user_id)
        full_flow = self._calc_full_flow_for_month(txns, user_id)

        # lifestyle_indicator: avg basic_flow / avg regular_income over last 3 completed months
        basic_flows: list[Decimal] = []
        regular_incomes: list[Decimal] = []
        for n in range(1, 4):
            prev = _prev_month(current, n)
            prev_txns = self._get_month_transactions(user_id, prev)
            if prev_txns:
                basic_flows.append(self._calc_basic_flow_for_month(prev_txns, user_id))
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
            prev_basic = self._calc_basic_flow_for_month(prev_txns, user_id)
            trend = _round2(basic_flow - prev_basic)

        return {
            "basic_flow": basic_flow,
            "full_flow": full_flow,
            "lifestyle_indicator": lifestyle_indicator,
            "zone": zone,
            "trend": trend,
        }

    # ── 4. Capital metric ────────────────────────────────────────────────────

    def calculate_capital(self, user_id: int) -> dict:
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

        # Trend: capital_trend = null for MVP (no historical snapshots)
        return {
            "capital": capital,
            "trend": None,
        }

    # ── 5. DTI metric ────────────────────────────────────────────────────────

    def calculate_dti(self, user_id: int) -> dict:
        today = date.today()
        current = date(today.year, today.month, 1)
        prev_month = _prev_month(current, 1)

        # Numerator: credit payments from the *previous* completed month.
        # If no payments in prev month, fall back to the most recent payment
        # per credit account, then to account.monthly_payment.
        credit_accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.is_active.is_(True),
                Account.account_type.in_(("credit", "credit_card", "installment_card")),
            )
            .all()
        )
        credit_account_ids = {acc.id for acc in credit_accounts}

        # Fetch ALL credit_payment transactions (regardless of affects_analytics)
        # because credit payments are often marked affects_analytics=False
        # but must still be counted for DTI.
        all_credit_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.operation_type == "credit_payment",
            )
            .all()
        )

        # Collect credit_payments from the previous month
        prev_month_start = _month_start_dt(prev_month)
        prev_month_end = _month_end_dt(prev_month)
        prev_month_payment_by_account: dict[int, Decimal] = {}
        for tx in all_credit_txns:
            account_id = getattr(tx, "credit_account_id", None) or getattr(tx, "target_account_id", None)
            if account_id is None or account_id not in credit_account_ids:
                continue
            if prev_month_start <= tx.transaction_date <= prev_month_end:
                prev_month_payment_by_account[account_id] = (
                    prev_month_payment_by_account.get(account_id, Decimal("0"))
                    + Decimal(str(tx.amount))
                )

        # Fallback: most recent payment per account (across all history)
        last_payment_by_account: dict[int, Decimal] = {}
        last_payment_date_by_account: dict[int, object] = {}
        for tx in all_credit_txns:
            account_id = getattr(tx, "credit_account_id", None) or getattr(tx, "target_account_id", None)
            if account_id is None or account_id not in credit_account_ids:
                continue
            tx_date = tx.transaction_date
            existing_date = last_payment_date_by_account.get(account_id)
            if existing_date is None or tx_date > existing_date:
                last_payment_by_account[account_id] = Decimal(str(tx.amount))
                last_payment_date_by_account[account_id] = tx_date

        monthly_payments = Decimal("0")
        for acc in credit_accounts:
            # Priority: prev month payment → latest historical payment → account fallback
            payment = prev_month_payment_by_account.get(acc.id)
            if payment is None or payment == 0:
                payment = last_payment_by_account.get(acc.id)
            if payment is None or payment == 0:
                fallback = getattr(acc, "monthly_payment", None)
                if fallback is not None:
                    payment = Decimal(str(fallback))
            if payment and payment > 0:
                monthly_payments += payment

        # Denominator: avg regular income over last 3 completed months
        regular_incomes: list[Decimal] = []
        all_incomes: list[Decimal] = []
        for n in range(1, 4):
            prev = _prev_month(current, n)
            prev_txns = self._get_month_transactions(user_id, prev)
            ri = self._calc_regular_income_for_month(prev_txns)
            regular_incomes.append(ri)
            # Fallback: also compute total income (all types)
            ai = sum(
                (Decimal(str(tx.amount)) for tx in prev_txns
                 if tx.type == "income"
                 and tx.operation_type not in ("transfer", "credit_early_repayment")),
                Decimal("0"),
            )
            all_incomes.append(ai)

        total_income = sum(regular_incomes, Decimal("0"))
        months_with_data = sum(1 for r in regular_incomes if r > 0)
        avg_regular_income = (
            _round2(total_income / Decimal(str(months_with_data)))
            if months_with_data > 0 else Decimal("0")
        )

        # Fallback: if no regular income (categories may lack regularity="regular"),
        # use all income so DTI at least shows an approximate value
        used_fallback = False
        if avg_regular_income == 0:
            total_all = sum(all_incomes, Decimal("0"))
            months_all = sum(1 for a in all_incomes if a > 0)
            if months_all > 0:
                avg_regular_income = _round2(total_all / Decimal(str(months_all)))
                used_fallback = True

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

    # ── 6. Reserve metric ────────────────────────────────────────────────────

    def calculate_reserve(self, user_id: int) -> dict:
        # Numerator: available liquid cash (regular + cash accounts with positive balance)
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

        # Denominator: avg monthly outflow over last 3-6 completed months
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
                 and tx.operation_type not in ("transfer", "credit_early_repayment")
                 and self._is_real_expense(tx, user_id)),
                Decimal("0"),
            )
            # Add credit payments too
            outflow += sum(
                (Decimal(str(tx.amount)) for tx in prev_txns
                 if tx.operation_type == "credit_payment"),
                Decimal("0"),
            )
            monthly_outflows.append(outflow)

        # Use 3 months if <6 months of data, otherwise 6
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

    # ── 7. FI-score (new weights) ────────────────────────────────────────────

    def _calc_fi_score(self, flow: dict, capital: dict, dti: dict, reserve: dict) -> float:
        # flow_score: min(lifestyle_indicator / 20 * 10, 10)
        li = flow.get("lifestyle_indicator")
        if li is not None:
            flow_score = min(li / 20 * 10, 10)
            if flow_score < 0:
                flow_score = 0
        else:
            flow_score = 5.0  # neutral

        # capital_score: trend-based. null -> 5 (neutral)
        trend = capital.get("trend")
        if trend is not None:
            if trend > 0:
                capital_score = min(float(trend) / 10000 * 10, 10)  # rough target
            else:
                capital_score = 0
        else:
            capital_score = 5.0

        # dti_score: max(10 - (dti / 6), 0)
        dti_pct = dti.get("dti_percent")
        if dti_pct is not None:
            dti_score = max(10 - (dti_pct / 6), 0)
        else:
            dti_score = 10.0  # no debt = perfect

        # reserve_score: min(months / 6 * 10, 10)
        months = reserve.get("months")
        if months is not None:
            reserve_score = min(months / 6 * 10, 10)
        else:
            reserve_score = 0

        fi_score = (
            flow_score * 0.25
            + capital_score * 0.30
            + dti_score * 0.20
            + reserve_score * 0.25
        )
        return round(fi_score, 1)

    # ── 8. Health recommendations ──────────────────────────────────────────

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

    METRIC_TIEBREAK = {"reserve": 0, "dti": 1, "flow": 2, "capital": 3}

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

    def _build_recommendations(self, flow: dict, capital: dict, dti: dict, reserve: dict) -> tuple[str, list[dict]]:
        metric_zones = {
            "flow": flow.get("zone", "healthy"),
            "capital": "green" if capital.get("trend") is None or capital.get("trend", 0) >= 0 else "red",
            "dti": dti.get("zone") or "normal",
            "reserve": reserve.get("zone") or "normal",
        }

        # Add capital declining recommendation
        if capital.get("trend") is not None and capital["trend"] < 0:
            metric_zones["capital"] = "danger"

        # Find weakest metric
        sorted_metrics = sorted(
            metric_zones.items(),
            key=lambda x: (self.ZONE_PRIORITY.get(x[1], 5), self.METRIC_TIEBREAK.get(x[0], 3)),
        )
        weakest_metric = sorted_metrics[0][0]

        # Build recommendations
        recs = []
        for metric, zone in sorted_metrics:
            zone_priority = self.ZONE_PRIORITY.get(zone, 5)
            if zone_priority >= 4:
                continue  # skip green zones

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

            # Special: capital declining
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

    # ── 9. Summary ───────────────────────────────────────────────────────────

    def calculate_metrics_summary(self, user_id: int) -> dict:
        today = date.today()
        flow = self.calculate_flow(user_id, today.year, today.month)
        capital = self.calculate_capital(user_id)
        dti = self.calculate_dti(user_id)
        reserve = self.calculate_reserve(user_id)
        fi_score = self._calc_fi_score(flow, capital, dti, reserve)

        return {
            "flow": flow,
            "capital": capital,
            "dti": dti,
            "reserve": reserve,
            "fi_score": fi_score,
        }

    def calculate_health_summary(self, user_id: int) -> dict:
        summary = self.calculate_metrics_summary(user_id)
        fi_score = summary["fi_score"]
        fi_zone = self._get_fi_zone(fi_score)
        weakest_metric, recommendations = self._build_recommendations(
            summary["flow"], summary["capital"], summary["dti"], summary["reserve"]
        )
        return {
            "metrics": summary,
            "fi_score": fi_score,
            "fi_zone": fi_zone,
            "weakest_metric": weakest_metric,
            "recommendations": recommendations,
        }
