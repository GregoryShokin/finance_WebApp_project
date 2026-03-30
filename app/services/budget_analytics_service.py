from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.budget_alert import BudgetAlert
from app.models.category import Category
from app.models.transaction import Transaction


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BudgetProgressItem:
    category_id: int
    category_name: str
    planned_amount: Decimal
    spent_amount: Decimal
    remaining: Decimal
    percent_used: float  # 0–100+


@dataclass
class AlertCreated:
    alert_type: str
    category_id: int | None
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_bounds(month: date) -> tuple[date, date]:
    """Returns (first_day, last_day) for the month of the given date."""
    first = month.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    last = first.replace(day=last_day)
    return first, last


def _month_start_dt(month: date) -> datetime:
    first, _ = _month_bounds(month)
    return datetime(first.year, first.month, first.day, tzinfo=timezone.utc)


def _month_end_dt(month: date) -> datetime:
    _, last = _month_bounds(month)
    return datetime(last.year, last.month, last.day, 23, 59, 59, tzinfo=timezone.utc)


def _shift_months(d: date, delta: int) -> date:
    """Shift date by `delta` months (negative = back)."""
    month = d.month + delta
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return d.replace(year=year, month=month, day=1)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Service ───────────────────────────────────────────────────────────────────

class BudgetAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── internal queries ──────────────────────────────────────────────────────

    def _expense_categories(self, user_id: int) -> list[Category]:
        return (
            self.db.query(Category)
            .filter(Category.user_id == user_id, Category.kind == "expense")
            .all()
        )

    def _spent_by_category(
        self,
        user_id: int,
        category_id: int,
        date_from: datetime,
        date_to: datetime,
    ) -> Decimal:
        rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.category_id == category_id,
                Transaction.type == "expense",
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .all()
        )
        return sum((Decimal(str(tx.amount)) for tx in rows), Decimal("0"))

    def _avg_monthly_expense(
        self, user_id: int, category_id: int, base_month: date, months: int = 3
    ) -> Decimal:
        """Average monthly spending for `months` full months before `base_month`."""
        total = Decimal("0")
        for i in range(1, months + 1):
            m = _shift_months(base_month, -i)
            total += self._spent_by_category(
                user_id, category_id, _month_start_dt(m), _month_end_dt(m)
            )
        return _round2(total / months)

    def _existing_budget(
        self, user_id: int, category_id: int, month: date
    ) -> Budget | None:
        first, _ = _month_bounds(month)
        return (
            self.db.query(Budget)
            .filter(
                Budget.user_id == user_id,
                Budget.category_id == category_id,
                Budget.month == first,
            )
            .first()
        )

    def _alert_exists_today(
        self,
        user_id: int,
        alert_type: str,
        category_id: int | None,
    ) -> bool:
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        q = self.db.query(BudgetAlert).filter(
            BudgetAlert.user_id == user_id,
            BudgetAlert.alert_type == alert_type,
            BudgetAlert.triggered_at >= today_start,
        )
        if category_id is not None:
            q = q.filter(BudgetAlert.category_id == category_id)
        else:
            q = q.filter(BudgetAlert.category_id.is_(None))
        return q.first() is not None

    def _create_alert(
        self,
        user_id: int,
        alert_type: str,
        message: str,
        category_id: int | None = None,
    ) -> BudgetAlert:
        alert = BudgetAlert(
            user_id=user_id,
            alert_type=alert_type,
            category_id=category_id,
            message=message,
        )
        self.db.add(alert)
        self.db.flush()
        return alert

    # ── 1. generate_budget_for_month ──────────────────────────────────────────

    def generate_budget_for_month(self, user_id: int, month: date) -> list[Budget]:
        """
        Creates auto-generated Budget records for all expense categories.
        Skips categories that already have a Budget record for this month.
        planned_amount = average spending over the previous 3 months.
        If there is no history, planned_amount = 0 (still creates the record).
        """
        first, _ = _month_bounds(month)
        categories = self._expense_categories(user_id)
        created: list[Budget] = []

        for cat in categories:
            if self._existing_budget(user_id, cat.id, first):
                continue

            avg = self._avg_monthly_expense(user_id, cat.id, first, months=3)
            budget = Budget(
                user_id=user_id,
                category_id=cat.id,
                month=first,
                planned_amount=avg,
                auto_generated=True,
            )
            self.db.add(budget)
            created.append(budget)

        self.db.commit()
        for b in created:
            self.db.refresh(b)

        return created

    # ── 2. get_budget_progress ────────────────────────────────────────────────

    def get_budget_progress(self, user_id: int, month: date) -> list[BudgetProgressItem]:
        """
        Returns budget progress for every expense category that has a Budget
        record for the given month.
        """
        first, _ = _month_bounds(month)
        budgets = (
            self.db.query(Budget)
            .filter(Budget.user_id == user_id, Budget.month == first)
            .all()
        )

        result: list[BudgetProgressItem] = []
        for b in budgets:
            cat = self.db.get(Category, b.category_id)
            cat_name = cat.name if cat else f"Категория {b.category_id}"

            spent = self._spent_by_category(
                user_id, b.category_id, _month_start_dt(first), _month_end_dt(first)
            )
            planned = Decimal(str(b.planned_amount))
            remaining = _round2(planned - spent)
            pct = float(spent / planned * 100) if planned > 0 else (100.0 if spent > 0 else 0.0)

            result.append(
                BudgetProgressItem(
                    category_id=b.category_id,
                    category_name=cat_name,
                    planned_amount=_round2(planned),
                    spent_amount=_round2(spent),
                    remaining=remaining,
                    percent_used=round(pct, 2),
                )
            )

        return sorted(result, key=lambda x: x.percent_used, reverse=True)

    # ── 3. check_and_create_alerts ────────────────────────────────────────────

    def check_and_create_alerts(self, user_id: int) -> list[AlertCreated]:
        """
        Checks three conditions and creates BudgetAlert records when triggered,
        deduplicating by (alert_type, category_id, today).

        Conditions:
          A) budget_80_percent  — percent_used > 80% for any budgeted category
          B) anomaly            — current month spending > 150% of 3-month average
          C) month_end_forecast — projected month-end balance < 0
        """
        today = date.today()
        month_first, month_last = _month_bounds(today)
        days_in_month = month_last.day
        days_passed = max(today.day, 1)

        created: list[AlertCreated] = []

        # ── A & B: per-category checks ────────────────────────────────────────
        progress = self.get_budget_progress(user_id, today)

        for item in progress:
            # A) Budget 80%
            if item.percent_used > 80:
                if not self._alert_exists_today(user_id, "budget_80_percent", item.category_id):
                    msg = (
                        f"Категория «{item.category_name}»: использовано "
                        f"{item.percent_used:.0f}% бюджета "
                        f"({item.spent_amount:,.0f} из {item.planned_amount:,.0f} ₽)."
                    )
                    self._create_alert(user_id, "budget_80_percent", msg, item.category_id)
                    created.append(AlertCreated("budget_80_percent", item.category_id, msg))

            # B) Anomaly: current spending > 150% of 3-month average
            avg = self._avg_monthly_expense(user_id, item.category_id, today, months=3)
            if avg > 0 and item.spent_amount > avg * Decimal("1.5"):
                if not self._alert_exists_today(user_id, "anomaly", item.category_id):
                    excess_pct = float(item.spent_amount / avg * 100) - 100
                    msg = (
                        f"Аномальные расходы в «{item.category_name}»: "
                        f"{item.spent_amount:,.0f} ₽ — на {excess_pct:.0f}% выше "
                        f"среднего за 3 месяца ({avg:,.0f} ₽)."
                    )
                    self._create_alert(user_id, "anomaly", msg, item.category_id)
                    created.append(AlertCreated("anomaly", item.category_id, msg))

        # ── C) Month-end forecast ─────────────────────────────────────────────
        if not self._alert_exists_today(user_id, "month_end_forecast", None):
            # Total income this month (analytics)
            income_rows = (
                self.db.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.type == "income",
                    Transaction.affects_analytics.is_(True),
                    Transaction.transaction_date >= _month_start_dt(today),
                    Transaction.transaction_date <= _month_end_dt(today),
                )
                .all()
            )
            total_income = sum(
                (Decimal(str(tx.amount)) for tx in income_rows), Decimal("0")
            )

            # Total expense this month (analytics)
            expense_rows = (
                self.db.query(Transaction)
                .filter(
                    Transaction.user_id == user_id,
                    Transaction.type == "expense",
                    Transaction.affects_analytics.is_(True),
                    Transaction.transaction_date >= _month_start_dt(today),
                    Transaction.transaction_date <= _month_end_dt(today),
                )
                .all()
            )
            total_expense = sum(
                (Decimal(str(tx.amount)) for tx in expense_rows), Decimal("0")
            )

            # Daily expense rate → projected total for the month
            daily_expense_rate = total_expense / days_passed
            projected_expense = _round2(daily_expense_rate * days_in_month)
            projected_balance = _round2(total_income - projected_expense)

            if projected_balance < 0:
                msg = (
                    f"Прогноз на конец месяца: дефицит {abs(projected_balance):,.0f} ₽. "
                    f"Доходы {total_income:,.0f} ₽, прогнозируемые расходы "
                    f"{projected_expense:,.0f} ₽ (на основе {days_passed} дней)."
                )
                self._create_alert(user_id, "month_end_forecast", msg, None)
                created.append(AlertCreated("month_end_forecast", None, msg))

        self.db.commit()
        return created
