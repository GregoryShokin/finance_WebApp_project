from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

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
