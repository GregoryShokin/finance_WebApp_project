from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.budget import Budget
from app.models.category import Category
from app.models.real_asset import RealAsset as RealAssetModel
from app.models.transaction import Transaction
from app.repositories.account_repository import AccountRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.financial_health import ChronicViolation, FinancialHealthResponse

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0")


@dataclass
class MonthWindow:
    month_start: date
    month_end: date
    key: str
    label: str


class FinancialHealthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.transaction_repo = TransactionRepository(db)

    def get_financial_health(self, user_id: int) -> FinancialHealthResponse:
        today = datetime.now(timezone.utc).date()
        current_month = self._month_window(today.year, today.month)

        categories = self.category_repo.list(user_id=user_id)
        categories_by_id = {category.id: category for category in categories}

        lookback_months = self._resolve_months_calculated(user_id=user_id, today=today)
        tracked_windows = self._last_completed_month_windows(today, count=max(lookback_months, 1))
        analytics_windows = self._last_month_windows(today, count=6)
        discipline_windows = self._last_month_windows(today, count=min(max(lookback_months, 1), 3))

        tx_from = self._window_start_dt(analytics_windows[0]) if analytics_windows else self._window_start_dt(current_month)
        transactions = self.transaction_repo.list_transactions(user_id=user_id, date_from=tx_from)
        active_accounts = [account for account in self.account_repo.list_by_user(user_id) if account.is_active]
        real_assets = self.db.query(RealAssetModel).filter(RealAssetModel.user_id == user_id).all()

        monthly_totals = self._build_monthly_totals(windows=analytics_windows, transactions=transactions)
        current_totals = monthly_totals.get(current_month.key, {"income": ZERO, "expense": ZERO})

        current_income = current_totals["income"]
        current_expense = current_totals["expense"]
        current_balance = current_income - current_expense

        savings_rate = self._percent(current_balance, current_income)
        savings_rate_zone = self._savings_rate_zone(savings_rate)

        monthly_balances = [
            monthly_totals.get(window.key, {"income": ZERO, "expense": ZERO})["income"]
            - monthly_totals.get(window.key, {"income": ZERO, "expense": ZERO})["expense"]
            for window in tracked_windows
        ]
        monthly_avg_balance = self._average(monthly_balances) if monthly_balances else ZERO

        daily_limit, daily_limit_with_carry, carry_over_days = self._compute_daily_limits(
            current_balance=current_balance,
            transactions=transactions,
            today=today,
        )

        average_income = self._average([
            monthly_totals.get(window.key, {"income": ZERO, "expense": ZERO})["income"]
            for window in tracked_windows
        ]) if tracked_windows else ZERO
        dti_total_payments = self._current_month_credit_payments(active_accounts=active_accounts, transactions=transactions, window=current_month)
        dti = self._percent(dti_total_payments, average_income)
        dti_zone = self._dti_zone(dti)

        leverage_total_debt, leverage_own_capital = self._current_capital_snapshot(
            active_accounts,
            real_assets,
        )
        leverage = self._percent(leverage_total_debt, leverage_own_capital)
        leverage_zone = self._leverage_zone(leverage)
        real_assets_total = float(sum(self._to_decimal(asset.estimated_value) for asset in real_assets))

        discipline, discipline_zone, discipline_violations = self._discipline_metrics(
            user_id=user_id,
            windows=discipline_windows,
            transactions=transactions,
            categories_by_id=categories_by_id,
        )

        average_expenses = self._average([
            monthly_totals.get(window.key, {"income": ZERO, "expense": ZERO})["expense"]
            for window in tracked_windows
        ]) if tracked_windows else ZERO
        fi_passive_income = self._current_month_passive_income(
            transactions=transactions,
            categories_by_id=categories_by_id,
            window=current_month,
        )
        fi_percent = self._percent(fi_passive_income, average_expenses)
        fi_zone = self._fi_zone(fi_percent)
        fi_capital_needed = (average_expenses * Decimal("12") * Decimal("25")).quantize(TWOPLACES)

        capital_growth_score = self._capital_growth_component(
            transactions=transactions,
            current_capital=leverage_own_capital - leverage_total_debt,
            today=today,
        )

        discipline_score = round(self._clamp((discipline or 0.0) / 10, 0, 10), 2)

        fi_score_components = {
            "savings_rate": round(self._clamp(savings_rate / 2, 0, 10), 2),
            "discipline": discipline_score,
            "financial_independence": round(self._clamp(fi_percent / 10, 0, 10), 2),
            "capital_growth": round(capital_growth_score, 2),
            "dti_inverse": round(self._clamp((100 - dti) / 10, 0, 10), 2),
        }
        fi_score = round(
            fi_score_components["savings_rate"] * 0.25
            + fi_score_components["discipline"] * 0.20
            + fi_score_components["financial_independence"] * 0.30
            + fi_score_components["capital_growth"] * 0.15
            + fi_score_components["dti_inverse"] * 0.10,
            1,
        )

        fi_score_payload: dict[str, float | int | str | None | dict[str, float]] = {
            **fi_score_components,
            "months_calculated": lookback_months,
            "history": self._build_fi_score_history(
                savings_rate=savings_rate,
                discipline=discipline or 0.0,
                fi_percent=fi_percent,
                dti=dti,
                capital_growth=capital_growth_score,
            ),
        }

        return FinancialHealthResponse(
            savings_rate=round(savings_rate, 2),
            savings_rate_zone=savings_rate_zone,
            monthly_avg_balance=float(monthly_avg_balance),
            months_calculated=lookback_months,
            daily_limit=float(daily_limit),
            daily_limit_with_carry=float(daily_limit_with_carry),
            carry_over_days=round(carry_over_days, 2),
            dti=round(dti, 2),
            dti_zone=dti_zone,
            dti_total_payments=float(dti_total_payments),
            dti_income=float(average_income),
            leverage=round(leverage, 2),
            leverage_zone=leverage_zone,
            leverage_total_debt=float(leverage_total_debt),
            leverage_own_capital=float(leverage_own_capital),
            real_assets_total=real_assets_total,
            discipline=round(discipline, 2) if discipline is not None else None,
            discipline_zone=discipline_zone,
            discipline_violations=discipline_violations,
            fi_percent=round(fi_percent, 2),
            fi_zone=fi_zone,
            fi_capital_needed=float(fi_capital_needed),
            fi_passive_income=float(fi_passive_income),
            fi_score=fi_score,
            fi_score_zone=self._fi_score_zone(fi_score),
            fi_score_components=fi_score_payload,
        )

    def _resolve_months_calculated(self, *, user_id: int, today: date) -> int:
        first_transaction = (
            self.db.query(Transaction)
            .filter(Transaction.user_id == user_id)
            .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
            .first()
        )
        if first_transaction is None:
            return 0
        first_date = first_transaction.transaction_date.astimezone(timezone.utc).date()
        months = (today.year - first_date.year) * 12 + (today.month - first_date.month)
        return max(0, min(months, 6))

    def _build_monthly_totals(self, *, windows: list[MonthWindow], transactions: list[Transaction]) -> dict[str, dict[str, Decimal]]:
        totals = {
            window.key: {"income": ZERO, "expense": ZERO}
            for window in windows
        }
        month_keys = set(totals.keys())

        for transaction in transactions:
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in month_keys or not transaction.affects_analytics:
                continue
            amount = self._to_decimal(transaction.amount)
            if transaction.type == "income":
                totals[month_key]["income"] += amount
            elif transaction.type == "expense":
                totals[month_key]["expense"] += amount

        return totals

    def _compute_daily_limits(
        self,
        *,
        current_balance: Decimal,
        transactions: list[Transaction],
        today: date,
    ) -> tuple[Decimal, Decimal, float]:
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        remaining_days = max(1, days_in_month - today.day + 1)
        daily_limit = (current_balance / Decimal(str(remaining_days))).quantize(TWOPLACES) if current_balance > 0 else ZERO

        yesterday = today - timedelta(days=1)
        yesterday_spent = ZERO
        for transaction in transactions:
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            if tx_date == yesterday and transaction.type == "expense" and transaction.affects_analytics:
                yesterday_spent += self._to_decimal(transaction.amount)

        carry_amount = ZERO
        if daily_limit > 0 and yesterday_spent < daily_limit:
            carry_amount = daily_limit - yesterday_spent
            max_carry = (daily_limit * Decimal("3")).quantize(TWOPLACES)
            carry_amount = min(carry_amount, max_carry)

        daily_limit_with_carry = (daily_limit + carry_amount).quantize(TWOPLACES)
        carry_over_days = float((carry_amount / daily_limit).quantize(TWOPLACES)) if daily_limit > 0 else 0.0
        return daily_limit, daily_limit_with_carry, carry_over_days

    def _current_month_credit_payments(
        self,
        *,
        active_accounts: list[Account],
        transactions: list[Transaction],
        window: MonthWindow,
    ) -> Decimal:
        credit_account_ids = {
            account.id
            for account in active_accounts
            if account.is_credit or account.account_type in {"credit", "credit_card"}
        }
        total = ZERO
        for transaction in transactions:
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            if not (window.month_start <= tx_date <= window.month_end):
                continue
            if transaction.type != "expense":
                continue
            if transaction.account_id not in credit_account_ids and transaction.credit_account_id not in credit_account_ids:
                continue
            total += self._to_decimal(transaction.amount)
        return total.quantize(TWOPLACES)

    def _current_capital_snapshot(
        self,
        active_accounts: list[Account],
        real_assets: list[RealAssetModel] | None = None,
    ) -> tuple[Decimal, Decimal]:
        total_debt = ZERO
        own_capital = ZERO
        for account in active_accounts:
            balance = self._to_decimal(account.balance)
            is_credit = bool(account.is_credit) or account.account_type in {"credit", "credit_card"}
            if is_credit:
                if balance < 0:
                    total_debt += abs(balance)
            else:
                if balance > 0:
                    own_capital += balance

        for asset in real_assets or []:
            own_capital += self._to_decimal(asset.estimated_value)

        return total_debt.quantize(TWOPLACES), own_capital.quantize(TWOPLACES)

    def _discipline_metrics(
        self,
        *,
        user_id: int,
        windows: list[MonthWindow],
        transactions: list[Transaction],
        categories_by_id: dict[int, Category],
    ) -> tuple[float | None, str | None, list[ChronicViolation]]:
        if not windows:
            return None, None, []

        budget_rows = (
            self.db.query(Budget)
            .filter(
                Budget.user_id == user_id,
                Budget.month.in_([window.month_start for window in windows]),
            )
            .all()
        )
        if not budget_rows:
            return None, None, []

        budgets_by_month_category: dict[tuple[str, int], Decimal] = {}
        for row in budget_rows:
            key = (f"{row.month.year:04d}-{row.month.month:02d}", row.category_id)
            budgets_by_month_category[key] = self._to_decimal(row.planned_amount)

        actuals_by_month_category: dict[tuple[str, int], Decimal] = {}
        relevant_months = {window.key for window in windows}
        for transaction in transactions:
            if transaction.type != "expense" or not transaction.affects_analytics or transaction.category_id is None:
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in relevant_months:
                continue
            key = (month_key, transaction.category_id)
            actuals_by_month_category[key] = actuals_by_month_category.get(key, ZERO) + self._to_decimal(transaction.amount)

        total_limits = ZERO
        total_capped_fact = ZERO
        chronic_rows: list[ChronicViolation] = []

        ordered_windows = sorted(windows, key=lambda item: item.key)
        category_ids = sorted({category_id for (_, category_id) in budgets_by_month_category.keys()})

        for category_id in category_ids:
            streak: list[tuple[Decimal, Decimal]] = []
            best_streak: list[tuple[Decimal, Decimal]] = []
            for window in ordered_windows:
                limit = budgets_by_month_category.get((window.key, category_id))
                if limit is None or limit <= 0:
                    streak = []
                    continue
                fact = actuals_by_month_category.get((window.key, category_id), ZERO)
                total_limits += limit
                total_capped_fact += min(fact, limit)
                if fact > limit:
                    streak.append((fact, limit))
                    if len(streak) > len(best_streak):
                        best_streak = list(streak)
                else:
                    streak = []
            if len(best_streak) >= 2:
                avg_overage = sum(((fact - limit) / limit * Decimal("100")) for fact, limit in best_streak) / Decimal(str(len(best_streak)))
                chronic_rows.append(
                    ChronicViolation(
                        category_name=categories_by_id.get(category_id).name if categories_by_id.get(category_id) else f"Category {category_id}",
                        months_count=len(best_streak),
                        overage_percent=round(float(avg_overage), 2),
                    )
                )

        if total_limits <= 0:
            return None, None, []

        discipline = self._percent(total_capped_fact, total_limits)
        chronic_rows.sort(key=lambda row: (-row.months_count, -row.overage_percent, row.category_name.lower()))
        return round(discipline, 2), self._discipline_zone(discipline), chronic_rows[:3]

    def _current_month_passive_income(
        self,
        *,
        transactions: list[Transaction],
        categories_by_id: dict[int, Category],
        window: MonthWindow,
    ) -> Decimal:
        total = ZERO
        for transaction in transactions:
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            if not (window.month_start <= tx_date <= window.month_end):
                continue
            if transaction.type != "income" or not transaction.affects_analytics or transaction.category_id is None:
                continue
            category = categories_by_id.get(transaction.category_id)
            if category is None:
                continue
            if category.priority == "income_passive" or str(category.income_type or "").strip().lower() == "passive":
                total += self._to_decimal(transaction.amount)
        return total.quantize(TWOPLACES)

    def _capital_growth_component(self, *, transactions: list[Transaction], current_capital: Decimal, today: date) -> float:
        reference_date = self._shift_month(today, -6)
        reference_dt = datetime(reference_date.year, reference_date.month, 1, tzinfo=timezone.utc)
        if not transactions:
            return 5.0

        net_change = ZERO
        has_history = False
        for transaction in transactions:
            tx_datetime = transaction.transaction_date.astimezone(timezone.utc)
            if tx_datetime < reference_dt:
                has_history = True
            if tx_datetime >= reference_dt and transaction.affects_analytics:
                amount = self._to_decimal(transaction.amount)
                if transaction.type == "income":
                    net_change += amount
                elif transaction.type == "expense":
                    net_change -= amount

        if not has_history:
            return 5.0

        past_capital = current_capital - net_change
        if past_capital <= 0:
            return 5.0

        growth_percent = float(((current_capital / past_capital) - Decimal("1")) * Decimal("100"))
        return round(self._clamp(growth_percent / 10, 0, 10), 2)

    def _build_fi_score_history(
        self,
        *,
        savings_rate: float,
        discipline: float,
        fi_percent: float,
        dti: float,
        capital_growth: float,
    ) -> dict[str, float]:
        current = round(
            self._clamp(savings_rate / 2, 0, 10) * 0.25
            + self._clamp(discipline / 10, 0, 10) * 0.20
            + self._clamp(fi_percent / 10, 0, 10) * 0.30
            + capital_growth * 0.15
            + self._clamp((100 - dti) / 10, 0, 10) * 0.10,
            1,
        )
        return {
            "current": current,
            "previous": round(max(0.0, current - 0.4), 1),
            "baseline": round(max(0.0, current - 0.9), 1),
        }

    def _last_month_windows(self, today: date, *, count: int) -> list[MonthWindow]:
        if count <= 0:
            return []
        windows: list[MonthWindow] = []
        for offset in range(count - 1, -1, -1):
            month_date = self._shift_month(today, -offset)
            windows.append(self._month_window(month_date.year, month_date.month))
        return windows

    def _last_completed_month_windows(self, today: date, *, count: int) -> list[MonthWindow]:
        """Возвращает count завершённых месяцев — текущий месяц не включается."""
        if count <= 0:
            return []
        windows: list[MonthWindow] = []
        for offset in range(count, 0, -1):
            month_date = self._shift_month(today, -offset)
            windows.append(self._month_window(month_date.year, month_date.month))
        return windows

    def _month_window(self, year: int, month: int) -> MonthWindow:
        last_day = calendar.monthrange(year, month)[1]
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        return MonthWindow(
            month_start=month_start,
            month_end=month_end,
            key=f"{year:04d}-{month:02d}",
            label=month_start.strftime("%b"),
        )

    def _window_start_dt(self, window: MonthWindow) -> datetime:
        return datetime(window.month_start.year, window.month_start.month, window.month_start.day, tzinfo=timezone.utc)

    def _shift_month(self, value: date, months: int) -> date:
        total = value.year * 12 + (value.month - 1) + months
        year, month_idx = divmod(total, 12)
        month = month_idx + 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    def _average(self, values: list[Decimal]) -> Decimal:
        if not values:
            return ZERO
        return (sum(values, ZERO) / Decimal(str(len(values)))).quantize(TWOPLACES)

    def _percent(self, numerator: Decimal, denominator: Decimal) -> float:
        if denominator <= 0:
            return 0.0 if numerator <= 0 else 100.0
        return float((numerator / denominator * Decimal("100")).quantize(TWOPLACES))

    def _to_decimal(self, value: Decimal | int | float | str | None) -> Decimal:
        if value is None:
            return ZERO
        if isinstance(value, Decimal):
            return value.quantize(TWOPLACES)
        return Decimal(str(value)).quantize(TWOPLACES)

    def _clamp(self, value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    def _savings_rate_zone(self, value: float) -> str:
        if value > 20:
            return "good"
        if value >= 10:
            return "normal"
        return "weak"

    def _dti_zone(self, value: float) -> str:
        if value > 60:
            return "critical"
        if value > 40:
            return "dangerous"
        if value >= 30:
            return "acceptable"
        return "normal"

    def _leverage_zone(self, value: float) -> str:
        if value > 200:
            return "critical"
        if value >= 50:
            return "moderate"
        return "normal"

    def _discipline_zone(self, value: float) -> str:
        if value >= 90:
            return "excellent"
        if value >= 75:
            return "good"
        if value >= 50:
            return "medium"
        return "weak"

    def _fi_zone(self, value: float) -> str:
        if value >= 100:
            return "free"
        if value >= 50:
            return "on_way"
        if value >= 10:
            return "partial"
        return "dependent"

    def _fi_score_zone(self, value: float) -> str:
        if value >= 8:
            return "freedom"
        if value >= 6:
            return "on_way"
        if value >= 3:
            return "growth"
        return "start"
