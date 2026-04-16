from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.budget import Budget
from app.models.budget_alert import BudgetAlert
from app.models.category import Category
from app.models.transaction import Transaction


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class BudgetProgressItem:
    category_id: int
    category_name: str
    category_kind: str           # income / expense
    category_priority: str       # expense_essential / expense_secondary / expense_target / income_active / income_passive
    income_type: str | None      # active / passive / None
    exclude_from_planning: bool  # True → one-time outflow, no plan
    planned_amount: Decimal
    suggested_amount: Decimal  # avg of last 3 months, computed at generation time
    spent_amount: Decimal
    remaining: Decimal
    percent_used: float  # 0–100+


@dataclass
class AlertCreated:
    alert_type: str
    category_id: int | None
    message: str


@dataclass
class FinancialIndependenceResult:
    passive_income: Decimal
    active_income: Decimal
    total_expenses: Decimal
    percent: float   # passive_income / total_expenses × 100
    status: str      # starting / growing / independent


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


def _adaptive_avg(values: list[Decimal]) -> Decimal:
    """
    Average over the 'available period':
    divisor = position of the furthest-back month that has non-zero data (1-indexed).
    Example: values=[590, 0, 0]  → divisor=1 → avg=590
             values=[400, 200, 0] → divisor=2 → avg=300
             values=[300, 400, 200] → divisor=3 → avg=300
             values=[0, 0, 600]  → divisor=3 → avg=200
    Returns 0 if all values are zero.
    """
    last_nonzero_idx = -1
    for i in range(len(values) - 1, -1, -1):
        if values[i] > 0:
            last_nonzero_idx = i
            break
    if last_nonzero_idx == -1:
        return Decimal("0")
    divisor = last_nonzero_idx + 1
    total = sum(values[:divisor], Decimal("0"))
    return _round2(total / divisor)


# ── Service ───────────────────────────────────────────────────────────────────

class BudgetAnalyticsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── internal queries ──────────────────────────────────────────────────────

    def _expense_categories(self, user_id: int) -> list[Category]:
        return (
            self.db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.kind == "expense",
                Category.exclude_from_planning.is_(False),
            )
            .all()
        )

    def _income_categories_by_type(
        self, user_id: int, income_type: str
    ) -> list[Category]:
        return (
            self.db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.kind == "income",
                Category.income_type == income_type,
            )
            .all()
        )

    def _income_categories_for_planning(self, user_id: int) -> list[Category]:
        return (
            self.db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.kind == "income",
                Category.exclude_from_planning.is_(False),
            )
            .all()
        )

    def _income_earned_by_category(
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
                Transaction.type == "income",
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .all()
        )
        return sum((Decimal(str(tx.amount)) for tx in rows), Decimal("0"))

    def _avg_monthly_income(
        self, user_id: int, category_id: int, base_month: date, months: int = 3
    ) -> Decimal:
        """
        Average monthly income over up to `months` prior months.
        Divisor = index of the last (furthest back) month that has non-zero income,
        so new categories with 1-2 months of history aren't penalised by empty months.
        """
        values: list[Decimal] = []
        for i in range(1, months + 1):
            m = _shift_months(base_month, -i)
            values.append(
                self._income_earned_by_category(
                    user_id, category_id, _month_start_dt(m), _month_end_dt(m)
                )
            )
        return _adaptive_avg(values)

    def _get_installment_card_ids(self, user_id: int) -> set[int]:
        """Get IDs of installment_card accounts — purchases on these are NOT real expenses."""
        rows = (
            self.db.query(Account.id)
            .filter(
                Account.user_id == user_id,
                Account.account_type == "installment_card",
            )
            .all()
        )
        return {r.id for r in rows}

    def _spent_by_category(
        self,
        user_id: int,
        category_id: int,
        date_from: datetime,
        date_to: datetime,
    ) -> Decimal:
        ic_ids = self._get_installment_card_ids(user_id)

        q = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.category_id == category_id,
                Transaction.type == "expense",
                Transaction.affects_analytics.is_(True),
                Transaction.converted_to_installment.is_(False),
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
                Transaction.operation_type.notin_(("transfer", "credit_early_repayment")),
            )
        )
        if ic_ids:
            q = q.filter(Transaction.account_id.notin_(ic_ids))

        rows = q.all()
        return sum((Decimal(str(tx.amount)) for tx in rows), Decimal("0"))

    def _avg_monthly_expense(
        self, user_id: int, category_id: int, base_month: date, months: int = 3
    ) -> Decimal:
        """
        Average monthly spending over up to `months` prior months.
        Divisor = index of the last (furthest back) month that has non-zero spending,
        so new categories with 1-2 months of history aren't penalised by empty months.
        """
        values: list[Decimal] = []
        for i in range(1, months + 1):
            m = _shift_months(base_month, -i)
            values.append(
                self._spent_by_category(
                    user_id, category_id, _month_start_dt(m), _month_end_dt(m)
                )
            )
        return _adaptive_avg(values)

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
        Idempotent: creates Budget records for all plannable categories
        (expense with exclude_from_planning=False, income with exclude_from_planning=False).
        Skips categories that already have a Budget record for this month.
        planned_amount = suggested_amount = adaptive avg of up to last 3 months.
        Categories with no transaction history still get a record with planned_amount=0,
        so they can be planned manually.
        """
        first, _ = _month_bounds(month)
        created: list[Budget] = []

        all_cats = self._expense_categories(user_id) + self._income_categories_for_planning(user_id)
        for cat in all_cats:
            if cat.kind == "income":
                avg = self._avg_monthly_income(user_id, cat.id, first, months=3)
            else:
                avg = self._avg_monthly_expense(user_id, cat.id, first, months=3)

            existing = self._existing_budget(user_id, cat.id, first)
            if existing:
                # Backfill suggested_amount for records created before migration 0021
                # (those rows have suggested_amount=0 from server_default)
                if existing.suggested_amount == Decimal("0") and avg > 0:
                    existing.suggested_amount = avg
                continue

            budget = Budget(
                user_id=user_id,
                category_id=cat.id,
                month=first,
                planned_amount=avg,
                suggested_amount=avg,
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

        date_from = _month_start_dt(first)
        date_to = _month_end_dt(first)

        planned_result: list[BudgetProgressItem] = []
        for b in budgets:
            cat = self.db.get(Category, b.category_id)
            if cat and cat.exclude_from_planning:
                continue
            cat_name = cat.name if cat else f"Категория {b.category_id}"
            cat_kind = cat.kind if cat else "expense"
            cat_priority = cat.priority if cat else "expense_essential"
            cat_income_type = cat.income_type if cat else None

            if cat_kind == "income":
                spent = self._income_earned_by_category(user_id, b.category_id, date_from, date_to)
            else:
                spent = self._spent_by_category(user_id, b.category_id, date_from, date_to)

            planned = Decimal(str(b.planned_amount))
            remaining = _round2(planned - spent)
            pct = float(spent / planned * 100) if planned > 0 else (100.0 if spent > 0 else 0.0)

            suggested = _round2(Decimal(str(b.suggested_amount))) if b.suggested_amount is not None else _round2(planned)

            planned_result.append(
                BudgetProgressItem(
                    category_id=b.category_id,
                    category_name=cat_name,
                    category_kind=cat_kind,
                    category_priority=cat_priority,
                    income_type=cat_income_type,
                    exclude_from_planning=False,
                    planned_amount=_round2(planned),
                    suggested_amount=suggested,
                    spent_amount=_round2(spent),
                    remaining=remaining,
                    percent_used=round(pct, 2),
                )
            )

        # Excluded expense categories — show actual spending only (one-time outflows)
        excluded_cats = (
            self.db.query(Category)
            .filter(
                Category.user_id == user_id,
                Category.kind == "expense",
                Category.exclude_from_planning.is_(True),
            )
            .all()
        )
        excluded_result: list[BudgetProgressItem] = []
        for cat in excluded_cats:
            spent = self._spent_by_category(user_id, cat.id, date_from, date_to)
            if spent == Decimal("0"):
                continue
            excluded_result.append(
                BudgetProgressItem(
                    category_id=cat.id,
                    category_name=cat.name,
                    category_kind="expense",
                    category_priority=cat.priority,
                    income_type=None,
                    exclude_from_planning=True,
                    planned_amount=Decimal("0"),
                    suggested_amount=Decimal("0"),
                    spent_amount=_round2(spent),
                    remaining=Decimal("0"),
                    percent_used=0.0,
                )
            )

        sorted_planned = sorted(planned_result, key=lambda x: x.percent_used, reverse=True)
        sorted_excluded = sorted(excluded_result, key=lambda x: x.spent_amount, reverse=True)
        return sorted_planned + sorted_excluded

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

        # ── A & B: per-category checks (expense only) ─────────────────────────
        progress = [
            item for item in self.get_budget_progress(user_id, today)
            if item.category_kind == "expense"
        ]

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

    # ── 4. get_financial_independence ─────────────────────────────────────────

    def get_financial_independence(
        self, user_id: int, month: date
    ) -> FinancialIndependenceResult:
        """
        Financial independence ratio = passive income / total expenses × 100.

        Passive income  — transactions in income categories with income_type="passive".
        Active income   — transactions in income categories with income_type="active".
        Total expenses  — expense transactions excluding exclude_from_planning categories.

        Status:
          starting    < 25 %
          growing    25–75 %
          independent > 75 %
        """
        date_from = _month_start_dt(month)
        date_to = _month_end_dt(month)

        # Category ID sets by income type
        passive_ids = {
            c.id for c in self._income_categories_by_type(user_id, "passive")
        }
        active_ids = {
            c.id for c in self._income_categories_by_type(user_id, "active")
        }
        excluded_expense_ids = {
            c.id
            for c in self.db.query(Category).filter(
                Category.user_id == user_id,
                Category.exclude_from_planning.is_(True),
            ).all()
        }

        # All analytics income + expense transactions for the month
        income_rows = (
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
        expense_rows = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= date_from,
                Transaction.transaction_date <= date_to,
            )
            .all()
        )

        passive_income = sum(
            (Decimal(str(tx.amount)) for tx in income_rows if tx.category_id in passive_ids),
            Decimal("0"),
        )
        active_income = sum(
            (Decimal(str(tx.amount)) for tx in income_rows if tx.category_id in active_ids),
            Decimal("0"),
        )
        total_expenses = sum(
            (
                Decimal(str(tx.amount))
                for tx in expense_rows
                if tx.category_id not in excluded_expense_ids
            ),
            Decimal("0"),
        )

        if total_expenses > 0:
            pct = float(passive_income / total_expenses * 100)
        else:
            pct = 100.0 if passive_income > 0 else 0.0

        if pct >= 75:
            fi_status = "independent"
        elif pct >= 25:
            fi_status = "growing"
        else:
            fi_status = "starting"

        return FinancialIndependenceResult(
            passive_income=_round2(passive_income),
            active_income=_round2(active_income),
            total_expenses=_round2(total_expenses),
            percent=round(pct, 2),
            status=fi_status,
        )
