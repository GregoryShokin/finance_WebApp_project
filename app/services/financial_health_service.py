from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.budget import Budget
from app.models.category import Category
from app.models.goal import Goal, GoalSystemKey
from app.models.real_asset import RealAsset as RealAssetModel
from app.models.transaction import Transaction
from app.repositories.account_repository import AccountRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.financial_health import ChronicUnderperformer, ChronicViolation, DirectionHeatmapRow, FIScoreComponents, FIScoreHistory, FinancialHealthResponse, MonthlyHealthSnapshot, UnplannedCategory

TWOPLACES = Decimal("0.01")
ZERO = Decimal("0")
HEATMAP_DIRECTIONS = [
    ("income_active", "Доходы активные"),
    ("income_passive", "Доходы пассивные"),
    ("expense_essential", "Обязательные"),
    ("expense_secondary", "Второстепенные"),
]
HEATMAP_DIRECTION_LABELS = dict(HEATMAP_DIRECTIONS)
RU_MONTH_LABELS = [
    "Янв",
    "Фев",
    "Мар",
    "Апр",
    "Май",
    "Июн",
    "Июл",
    "Авг",
    "Сен",
    "Окт",
    "Ноя",
    "Дек",
]


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
        discipline_windows = self._last_completed_month_windows(today, count=min(max(lookback_months, 1), 3))

        tx_from = self._window_start_dt(analytics_windows[0]) if analytics_windows else self._window_start_dt(current_month)
        transactions = self.transaction_repo.list_transactions(user_id=user_id, date_from=tx_from)
        active_accounts = [account for account in self.account_repo.list_by_user(user_id) if account.is_active]
        real_assets = self.db.query(RealAssetModel).filter(RealAssetModel.user_id == user_id).all()
        safety_goal = (
            self.db.query(Goal)
            .filter(Goal.user_id == user_id, Goal.system_key == GoalSystemKey.safety_buffer.value)
            .first()
        )

        monthly_totals = self._build_monthly_totals(
            windows=analytics_windows,
            transactions=transactions,
            categories_by_id=categories_by_id,
        )
        empty_totals = {"income": ZERO, "expense": ZERO, "essential": ZERO, "secondary": ZERO}
        current_totals = monthly_totals.get(current_month.key, empty_totals)

        current_income = current_totals["income"]
        current_expense = current_totals["expense"]
        current_balance = current_income - current_expense

        savings_rate = self._percent(current_balance, current_income)
        avg_savings_rate = self._average_savings_rate(
            windows=tracked_windows,
            monthly_totals=monthly_totals,
            fallback=savings_rate,
        )
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
        dti_total_payments = self._calc_dti_payments(
            active_accounts=active_accounts,
            transactions=transactions,
        )
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
        chronic_underperformers = self._build_chronic_underperformers(
            user_id=user_id,
            windows=tracked_windows,
            transactions=transactions,
            categories_by_id=categories_by_id,
        )
        unplanned_categories = self._build_unplanned_categories(
            user_id=user_id,
            windows=tracked_windows,
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
        fi_monthly_gap = max(average_expenses - fi_passive_income, ZERO).quantize(TWOPLACES)

        safety_buffer_score = self._safety_buffer_component(safety_goal=safety_goal)

        discipline_score = round(self._clamp((discipline or 0.0) / 10, 0, 10), 2)

        fi_score_components = FIScoreComponents(
            savings_rate=round(self._clamp(avg_savings_rate / 2, 0, 10), 2),
            discipline=discipline_score,
            financial_independence=round(self._clamp(fi_percent / 10, 0, 10), 2),
            safety_buffer=round(safety_buffer_score, 2),
            dti_inverse=round(self._clamp((100 - dti) / 10, 0, 10), 2),
        )
        fi_score = round(
            fi_score_components.savings_rate * 0.25
            + fi_score_components.discipline * 0.20
            + fi_score_components.financial_independence * 0.30
            + fi_score_components.safety_buffer * 0.15
            + fi_score_components.dti_inverse * 0.10,
            1,
        )

        fi_score_payload = FIScoreComponents(
            **fi_score_components.model_dump(exclude={"months_calculated", "history"}),
            months_calculated=lookback_months,
            history=FIScoreHistory(**self._build_fi_score_history(
                savings_rate=avg_savings_rate,
                discipline=discipline or 0.0,
                fi_percent=fi_percent,
                dti=dti,
                safety_buffer_score=safety_buffer_score,
            )),
        )
        monthly_history = self._build_monthly_history(
            user_id=user_id,
            windows=tracked_windows,
            transactions=transactions,
            monthly_totals=monthly_totals,
            categories_by_id=categories_by_id,
            safety_buffer_score=safety_buffer_score,
        )

        return FinancialHealthResponse(
            savings_rate=round(savings_rate, 2),
            avg_savings_rate=round(avg_savings_rate, 2),
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
            chronic_underperformers=chronic_underperformers,
            unplanned_categories=unplanned_categories,
            fi_percent=round(fi_percent, 2),
            fi_zone=fi_zone,
            fi_capital_needed=float(fi_capital_needed),
            fi_passive_income=float(fi_passive_income),
            fi_monthly_gap=float(fi_monthly_gap),
            fi_score=fi_score,
            fi_score_zone=self._fi_score_zone(fi_score),
            fi_score_components=fi_score_payload,
            monthly_history=monthly_history,
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

    def _build_monthly_totals(
        self,
        *,
        windows: list[MonthWindow],
        transactions: list[Transaction],
        categories_by_id: dict[int, Category],
    ) -> dict[str, dict[str, Decimal]]:
        totals = {
            window.key: {"income": ZERO, "expense": ZERO, "essential": ZERO, "secondary": ZERO}
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
                category = categories_by_id.get(transaction.category_id) if transaction.category_id is not None else None
                if category is None:
                    continue
                if category.priority == "expense_essential":
                    totals[month_key]["essential"] += amount
                elif category.priority == "expense_secondary":
                    totals[month_key]["secondary"] += amount

        return totals

    def _build_monthly_history(
        self,
        *,
        user_id: int,
        windows: list[MonthWindow],
        transactions: list[Transaction],
        monthly_totals: dict[str, dict[str, Decimal]],
        categories_by_id: dict[int, Category],
        safety_buffer_score: float,
    ) -> list[MonthlyHealthSnapshot]:
        if not windows:
            return []

        budget_rows = (
            self.db.query(Budget)
            .filter(
                Budget.user_id == user_id,
                Budget.month.in_([window.month_start for window in windows]),
            )
            .all()
        )
        planned_income_by_month: dict[str, Decimal] = {}
        planned_expenses_by_month: dict[str, Decimal] = {}
        planned_by_month_direction: dict[tuple[str, str], Decimal] = {}
        for row in budget_rows:
            key = f"{row.month.year:04d}-{row.month.month:02d}"
            category = categories_by_id.get(row.category_id)
            if category is None:
                continue
            priority = str(category.priority or "").strip().lower()
            if priority:
                direction_key = (key, priority)
                planned_by_month_direction[direction_key] = planned_by_month_direction.get(direction_key, ZERO) + self._to_decimal(row.planned_amount)
            if category.kind == "income":
                planned_income_by_month[key] = planned_income_by_month.get(key, ZERO) + self._to_decimal(row.planned_amount)
            elif category.kind == "expense":
                planned_expenses_by_month[key] = planned_expenses_by_month.get(key, ZERO) + self._to_decimal(row.planned_amount)

        actual_by_month_direction: dict[tuple[str, str], Decimal] = {}
        relevant_months = {window.key for window in windows}
        for transaction in transactions:
            if not transaction.affects_analytics or transaction.category_id is None:
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in relevant_months:
                continue
            category = categories_by_id.get(transaction.category_id)
            if category is None:
                continue
            priority = str(category.priority or "").strip().lower()
            if priority not in {"income_active", "income_passive", "expense_essential", "expense_secondary"}:
                continue
            direction_key = (month_key, priority)
            actual_by_month_direction[direction_key] = actual_by_month_direction.get(direction_key, ZERO) + self._to_decimal(transaction.amount)

        history: list[MonthlyHealthSnapshot] = []
        for window in windows:
            totals = monthly_totals.get(window.key, {"income": ZERO, "expense": ZERO, "essential": ZERO, "secondary": ZERO})
            income = totals["income"]
            essential = totals["essential"]
            secondary = totals["secondary"]
            planned_income = planned_income_by_month.get(window.key, ZERO)
            actual_income = income
            planned_expenses = planned_expenses_by_month.get(window.key, ZERO)
            actual_expenses = (essential + secondary).quantize(TWOPLACES)
            savings = (income - essential - secondary).quantize(TWOPLACES)
            savings_rate = self._percent(savings, income)
            essential_rate = self._percent(essential, income)
            secondary_rate = self._percent(secondary, income)
            dti_payments = self._credit_payments_for_window(transactions=transactions, window=window)
            dti = self._percent(dti_payments, income)
            discipline, _, _ = self._discipline_metrics(
                user_id=user_id,
                windows=[window],
                transactions=transactions,
                categories_by_id=categories_by_id,
            )
            passive_income = self._current_month_passive_income(
                transactions=transactions,
                categories_by_id=categories_by_id,
                window=window,
            )
            fi_percent = self._percent(passive_income, totals["expense"])
            fi_score = self._build_weighted_fi_score(
                savings_rate=savings_rate,
                discipline=discipline or 0.0,
                fi_percent=fi_percent,
                dti=dti,
                safety_buffer_score=safety_buffer_score,
            )
            direction_heatmap: list[DirectionHeatmapRow] = []
            for direction, label in HEATMAP_DIRECTIONS:
                planned = planned_by_month_direction.get((window.key, direction), ZERO)
                if direction == "expense_essential":
                    actual = essential
                elif direction == "expense_secondary":
                    actual = secondary
                else:
                    actual = actual_by_month_direction.get((window.key, direction), ZERO)
                fulfillment = -1.0 if planned <= ZERO else round(float((actual / planned * Decimal("100")).quantize(TWOPLACES)), 2)
                direction_heatmap.append(
                    DirectionHeatmapRow(
                        direction=direction,
                        label=label,
                        planned=float(planned),
                        actual=float(actual),
                        fulfillment=fulfillment,
                    )
                )
            history.append(
                MonthlyHealthSnapshot(
                    month=window.key,
                    label=window.label,
                    income=float(income),
                    essential=float(essential),
                    secondary=float(secondary),
                    planned_income=float(planned_income),
                    actual_income=float(actual_income),
                    planned_expenses=float(planned_expenses),
                    actual_expenses=float(actual_expenses),
                    savings=float(savings),
                    savings_rate=round(savings_rate, 2),
                    essential_rate=round(essential_rate, 2),
                    secondary_rate=round(secondary_rate, 2),
                    dti=round(dti, 2),
                    fi_score=fi_score,
                    discipline=round(discipline, 2) if discipline is not None else None,
                    direction_heatmap=direction_heatmap,
                )
            )
        return history

    def _average_savings_rate(
        self,
        *,
        windows: list[MonthWindow],
        monthly_totals: dict[str, dict[str, Decimal]],
        fallback: float,
    ) -> float:
        if not windows:
            return fallback
        values: list[float] = []
        for window in windows:
            totals = monthly_totals.get(window.key, {"income": ZERO, "expense": ZERO, "essential": ZERO, "secondary": ZERO})
            income = totals["income"]
            if income <= ZERO:
                continue
            balance = totals["income"] - totals["expense"]
            values.append(self._percent(balance, income))
        if not values:
            return fallback
        return round(sum(values) / len(values), 2)

    def _build_chronic_underperformers(
        self,
        *,
        user_id: int,
        windows: list[MonthWindow],
        transactions: list[Transaction],
        categories_by_id: dict[int, Category],
    ) -> list[ChronicUnderperformer]:
        if not windows:
            return []

        budget_rows = (
            self.db.query(Budget)
            .filter(
                Budget.user_id == user_id,
                Budget.month.in_([window.month_start for window in windows]),
            )
            .all()
        )
        if not budget_rows:
            return []

        budgets_by_month_category: dict[tuple[str, int], Decimal] = {}
        for row in budget_rows:
            budgets_by_month_category[(f"{row.month.year:04d}-{row.month.month:02d}", row.category_id)] = self._to_decimal(row.planned_amount)

        actuals_by_month_category: dict[tuple[str, int], Decimal] = {}
        relevant_months = {window.key for window in windows}
        for transaction in transactions:
            if not transaction.affects_analytics or transaction.category_id is None:
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in relevant_months:
                continue
            actuals_by_month_category[(month_key, transaction.category_id)] = actuals_by_month_category.get((month_key, transaction.category_id), ZERO) + self._to_decimal(transaction.amount)

        results: list[tuple[float, ChronicUnderperformer]] = []
        ordered_windows = sorted(windows, key=lambda item: item.key)
        category_ids = sorted({category_id for (_, category_id) in budgets_by_month_category.keys()})

        for category_id in category_ids:
            category = categories_by_id.get(category_id)
            if category is None:
                continue
            direction = str(category.priority or "").strip().lower()
            if direction not in HEATMAP_DIRECTION_LABELS:
                continue

            month_rows: list[tuple[str, Decimal, Decimal, float]] = []
            for window in ordered_windows:
                planned = budgets_by_month_category.get((window.key, category_id), ZERO)
                if planned <= ZERO:
                    continue
                actual = actuals_by_month_category.get((window.key, category_id), ZERO)
                fulfillment = float((actual / planned * Decimal("100")).quantize(TWOPLACES))
                problematic = fulfillment < 95 if direction.startswith("income") else fulfillment > 100
                if problematic:
                    month_rows.append((window.key, planned, actual, fulfillment))

            if len(month_rows) < 2:
                continue

            month_rows.sort(key=lambda item: item[0])
            consecutive: list[tuple[str, Decimal, Decimal, float]] = [month_rows[-1]]
            for row in reversed(month_rows[:-1]):
                if self._is_previous_month_key(row[0], consecutive[0][0]):
                    consecutive.insert(0, row)
                else:
                    break

            if len(consecutive) < 2:
                continue

            fulfillments = [row[3] for row in consecutive]
            first_value = fulfillments[0]
            last_value = fulfillments[-1]
            if direction.startswith("income"):
                if last_value > first_value + 5:
                    trend = "improving"
                elif last_value < first_value - 5:
                    trend = "worsening"
                else:
                    trend = "stable"
                severity = max(0.0, 95 - average(fulfillments)) * len(consecutive)
            else:
                if last_value < first_value - 5:
                    trend = "improving"
                elif last_value > first_value + 5:
                    trend = "worsening"
                else:
                    trend = "stable"
                severity = max(0.0, average(fulfillments) - 100) * len(consecutive)

            last_planned = consecutive[-1][1]
            last_actual = consecutive[-1][2]
            results.append((
                severity,
                ChronicUnderperformer(
                    category_id=category_id,
                    category_name=category.name,
                    direction=direction,
                    direction_label=HEATMAP_DIRECTION_LABELS[direction],
                    months_count=len(consecutive),
                    avg_fulfillment=round(average(fulfillments), 2),
                    trend=trend,
                    last_planned=float(last_planned),
                    last_actual=float(last_actual),
                ),
            ))

        results.sort(key=lambda item: (-item[0], -item[1].months_count, item[1].category_name.lower()))
        return [item[1] for item in results[:3]]

    def _build_unplanned_categories(
        self,
        *,
        user_id: int,
        windows: list[MonthWindow],
        transactions: list[Transaction],
        categories_by_id: dict[int, Category],
    ) -> list[UnplannedCategory]:
        if not windows:
            return []

        expense_categories = [
            category
            for category in categories_by_id.values()
            if getattr(category, "kind", None) == "expense"
        ]
        if not expense_categories:
            return []

        budget_rows = (
            self.db.query(Budget)
            .filter(
                Budget.user_id == user_id,
                Budget.month.in_([window.month_start for window in windows]),
                Budget.category_id.in_([category.id for category in expense_categories]),
            )
            .all()
        )
        budgeted_category_ids = {row.category_id for row in budget_rows}
        relevant_months = {window.key for window in windows}
        spending_by_category_month: dict[tuple[int, str], Decimal] = {}

        for transaction in transactions:
            if transaction.type != "expense" or not transaction.affects_analytics or transaction.category_id is None:
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in relevant_months:
                continue
            key = (transaction.category_id, month_key)
            spending_by_category_month[key] = spending_by_category_month.get(key, ZERO) + self._to_decimal(transaction.amount)

        result: list[UnplannedCategory] = []
        for category in expense_categories:
            if category.id in budgeted_category_ids:
                continue
            month_values = [
                amount
                for (category_id, _), amount in spending_by_category_month.items()
                if category_id == category.id and amount > ZERO
            ]
            months_with_spending = len(month_values)
            if months_with_spending < 2:
                continue
            avg_monthly_amount = self._average(month_values)
            if avg_monthly_amount < Decimal("1000"):
                continue
            direction = str(category.priority or "").strip().lower()
            result.append(
                UnplannedCategory(
                    category_id=category.id,
                    category_name=category.name,
                    direction=direction,
                    direction_label=HEATMAP_DIRECTION_LABELS.get(direction, category.name),
                    avg_monthly_amount=float(avg_monthly_amount),
                    months_with_spending=months_with_spending,
                )
            )

        result.sort(key=lambda item: (-item.avg_monthly_amount, item.category_name.lower()))
        return result[:5]

    def _is_previous_month_key(self, current_key: str, next_key: str) -> bool:
        current_date = date(int(current_key[:4]), int(current_key[5:7]), 1)
        expected_next = self._shift_month(current_date, 1)
        return next_key == f"{expected_next.year:04d}-{expected_next.month:02d}"

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

    def _calc_dti_payments(
        self,
        *,
        active_accounts: list[Account],
        transactions: list[Transaction],
    ) -> Decimal:
        """
        Р В Р Р‹Р РЋРЎвЂњР В РЎВР В РЎВР В Р’В°Р РЋР вЂљР В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р В Р’ВµР В Р’В¶Р В Р’ВµР В РЎВР В Р’ВµР РЋР С“Р РЋР РЏР РЋРІР‚РЋР В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р В РЎвЂ”Р В Р’В»Р В Р’В°Р РЋРІР‚С™Р РЋРІР‚ВР В Р’В¶ Р В РЎвЂ”Р В РЎвЂў Р В РЎвЂќР РЋР вЂљР В Р’ВµР В РўвЂР В РЎвЂР РЋРІР‚С™Р В Р’В°Р В РЎВ Р В РўвЂР В Р’В»Р РЋР РЏ DTI.

        Р В РІР‚СњР В Р’В»Р РЋР РЏ Р В РЎвЂќР В Р’В°Р В Р’В¶Р В РўвЂР В РЎвЂўР В РЎвЂ“Р В РЎвЂў Р В РЎвЂќР РЋР вЂљР В Р’ВµР В РўвЂР В РЎвЂР РЋРІР‚С™Р В Р вЂ¦Р В РЎвЂўР В РЎвЂ“Р В РЎвЂў Р РЋР С“Р РЋРІР‚РЋР РЋРІР‚ВР РЋРІР‚С™Р В Р’В°:
        1. Р В РЎСџР В РЎвЂўР РЋР С“Р В Р’В»Р В Р’ВµР В РўвЂР В Р вЂ¦Р В РЎвЂР В РІвЂћвЂ“ Р РЋРІР‚С›Р В Р’В°Р В РЎвЂќР РЋРІР‚С™Р В РЎвЂР РЋРІР‚РЋР В Р’ВµР РЋР С“Р В РЎвЂќР В РЎвЂР В РІвЂћвЂ“ credit_payment Р В РЎвЂР В Р’В· Р РЋРІР‚С™Р РЋР вЂљР В Р’В°Р В Р вЂ¦Р В Р’В·Р В Р’В°Р В РЎвЂќР РЋРІР‚В Р В РЎвЂР В РІвЂћвЂ“
        2. Р В РІР‚СћР РЋР С“Р В Р’В»Р В РЎвЂ Р В Р’ВµР В РЎвЂ“Р В РЎвЂў Р В Р вЂ¦Р В Р’ВµР РЋРІР‚С™ Р Р†Р вЂљРІР‚Сњ monthly_payment Р В Р вЂ  Р В РЎвЂќР В Р’В°Р РЋР вЂљР РЋРІР‚С™Р В РЎвЂўР РЋРІР‚РЋР В РЎвЂќР В Р’Вµ Р РЋР С“Р РЋРІР‚РЋР РЋРІР‚ВР РЋРІР‚С™Р В Р’В°
        3. Р В РІР‚СћР РЋР С“Р В Р’В»Р В РЎвЂ Р В Р вЂ¦Р В Р’ВµР РЋРІР‚С™ Р В РЎвЂ Р В Р’ВµР В РЎвЂ“Р В РЎвЂў Р Р†Р вЂљРІР‚Сњ 0
        """
        last_payment_by_account: dict[int, Decimal] = {}
        last_payment_date_by_account: dict[int, datetime] = {}

        for transaction in transactions:
            if transaction.operation_type != "credit_payment":
                continue
            account_id = transaction.credit_account_id or transaction.target_account_id
            if account_id is None:
                continue
            tx_date = transaction.transaction_date
            existing_date = last_payment_date_by_account.get(account_id)
            if existing_date is None or tx_date > existing_date:
                last_payment_by_account[account_id] = self._to_decimal(transaction.amount)
                last_payment_date_by_account[account_id] = tx_date

        total = ZERO
        for account in active_accounts:
            is_credit_account = (
                account.account_type in {"credit", "credit_card", "installment_card"}
                or bool(account.is_credit)
            )
            if not is_credit_account:
                continue

            payment = last_payment_by_account.get(account.id)
            if payment is None or payment == ZERO:
                fallback = getattr(account, "monthly_payment", None)
                if fallback is not None:
                    payment = self._to_decimal(fallback)

            if payment and payment > ZERO:
                total += payment

        return total.quantize(TWOPLACES)

    def _credit_payments_for_window(self, *, transactions: list[Transaction], window: MonthWindow) -> Decimal:
        total = ZERO
        for transaction in transactions:
            if transaction.operation_type != "credit_payment":
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            if window.month_start <= tx_date <= window.month_end:
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
            is_credit = bool(account.is_credit) or account.account_type in {"credit", "credit_card", "installment_card"}
            if is_credit:
                if balance < 0:
                    total_debt += abs(balance)
            elif account.account_type == "deposit":
                own_capital += balance
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
        """
        Дисциплина считается по 4 направлениям (direction), а не по категориям.

        Направления:
          - income_active:      доходы активные  → выполнение = min(fact/plan, 1)
          - income_passive:     доходы пассивные → выполнение = min(fact/plan, 1)
          - expense_essential:  обязательные     → выполнение = min(plan/fact, 1)
          - expense_secondary:  второстепенные   → выполнение = min(plan/fact, 1)

        Направление учитывается только если plan > 0.
        Если plan > 0 и fact == 0 — для доходов это 0% выполнения,
        для расходов — 100% (ничего не потратил, лимит соблюдён).
        Итог: среднее выполнение по направлениям у которых есть план,
        усреднённое по всем окнам.
        Chronic violations не меняются — оставь текущую логику по категориям.
        """
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

        # plan по направлениям за каждый месяц
        plan_by_month_direction: dict[tuple[str, str], Decimal] = {}
        for row in budget_rows:
            month_key = f"{row.month.year:04d}-{row.month.month:02d}"
            category = categories_by_id.get(row.category_id)
            if category is None:
                continue
            priority = str(category.priority or "").strip().lower()
            if priority not in {"income_active", "income_passive", "expense_essential", "expense_secondary"}:
                continue
            key = (month_key, priority)
            plan_by_month_direction[key] = plan_by_month_direction.get(key, ZERO) + self._to_decimal(row.planned_amount)

        if not plan_by_month_direction:
            return None, None, []

        # fact по направлениям за каждый месяц
        fact_by_month_direction: dict[tuple[str, str], Decimal] = {}
        relevant_months = {window.key for window in windows}
        for transaction in transactions:
            if not transaction.affects_analytics or transaction.category_id is None:
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in relevant_months:
                continue
            category = categories_by_id.get(transaction.category_id)
            if category is None:
                continue
            priority = str(category.priority or "").strip().lower()
            if priority not in {"income_active", "income_passive", "expense_essential", "expense_secondary"}:
                continue
            key = (month_key, priority)
            fact_by_month_direction[key] = fact_by_month_direction.get(key, ZERO) + self._to_decimal(transaction.amount)

        # считаем выполнение по каждому направлению в каждом окне
        # используем взвешенное среднее — вес = plan по направлению
        # чтобы мелкий пассивный доход (кэшбэк 2000 ₽) не перевешивал
        # крупные направления (активный доход 150 000 ₽)
        weighted_sum: float = 0.0
        total_weight: float = 0.0
        for window in windows:
            for direction in ("income_active", "income_passive", "expense_essential", "expense_secondary"):
                plan = plan_by_month_direction.get((window.key, direction), ZERO)
                if plan <= ZERO:
                    continue  # нет плана — направление не учитывается
                fact = fact_by_month_direction.get((window.key, direction), ZERO)
                is_income = direction.startswith("income_")
                if is_income:
                    score = float(min(fact / plan, Decimal("1")))
                else:
                    if fact <= ZERO:
                        score = 1.0
                    else:
                        score = float(min(plan / fact, Decimal("1")))
                weight = float(plan)
                weighted_sum += score * weight
                total_weight += weight

        if total_weight <= 0:
            return None, None, []

        discipline = round(weighted_sum / total_weight * 100, 2)

        # chronic violations — оставляем старую логику по категориям
        # собираем actuals по категориям для chronic
        budgets_by_month_category: dict[tuple[str, int], Decimal] = {}
        for row in budget_rows:
            month_key = f"{row.month.year:04d}-{row.month.month:02d}"
            key = (month_key, row.category_id)
            budgets_by_month_category[key] = self._to_decimal(row.planned_amount)

        actuals_by_month_category: dict[tuple[str, int], Decimal] = {}
        for transaction in transactions:
            if transaction.type != "expense" or not transaction.affects_analytics or transaction.category_id is None:
                continue
            tx_date = transaction.transaction_date.astimezone(timezone.utc).date()
            month_key = f"{tx_date.year:04d}-{tx_date.month:02d}"
            if month_key not in relevant_months:
                continue
            key = (month_key, transaction.category_id)
            actuals_by_month_category[key] = actuals_by_month_category.get(key, ZERO) + self._to_decimal(transaction.amount)

        chronic_rows: list[ChronicViolation] = []
        ordered_windows = sorted(windows, key=lambda w: w.key)
        category_ids = sorted({cat_id for (_, cat_id) in budgets_by_month_category.keys()})

        for category_id in category_ids:
            streak: list[tuple[Decimal, Decimal]] = []
            best_streak: list[tuple[Decimal, Decimal]] = []
            for window in ordered_windows:
                limit = budgets_by_month_category.get((window.key, category_id))
                if limit is None or limit <= ZERO:
                    streak = []
                    continue
                fact = actuals_by_month_category.get((window.key, category_id), ZERO)
                if fact > limit:
                    streak.append((fact, limit))
                    if len(streak) > len(best_streak):
                        best_streak = list(streak)
                else:
                    streak = []
            if len(best_streak) >= 2:
                avg_overage = sum(
                    ((f - l) / l * Decimal("100")) for f, l in best_streak
                ) / Decimal(str(len(best_streak)))
                category = categories_by_id.get(category_id)
                chronic_rows.append(
                    ChronicViolation(
                        category_name=category.name if category else f"Category {category_id}",
                        months_count=len(best_streak),
                        overage_percent=round(float(avg_overage), 2),
                    )
                )

        chronic_rows.sort(key=lambda r: (-r.months_count, -r.overage_percent, r.category_name.lower()))
        return discipline, self._discipline_zone(discipline), chronic_rows[:3]

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

    def _safety_buffer_component(self, *, safety_goal: Goal | None) -> float:
        if safety_goal is None:
            return 0.0
        target_amount = self._to_decimal(safety_goal.target_amount)
        if target_amount <= ZERO:
            return 0.0
        saved_amount = self._goal_saved_amount(goal_id=safety_goal.id)
        progress = float((saved_amount / target_amount).quantize(TWOPLACES)) if target_amount > ZERO else 0.0
        return round(self._clamp(progress * 10, 0, 10), 2)

    def _goal_saved_amount(self, *, goal_id: int) -> Decimal:
        total = (
            self.db.query(Transaction)
            .filter(Transaction.goal_id == goal_id)
            .with_entities(Transaction.amount)
            .all()
        )
        return sum((self._to_decimal(row.amount) for row in total), ZERO).quantize(TWOPLACES)

    def _build_weighted_fi_score(
        self,
        *,
        savings_rate: float,
        discipline: float,
        fi_percent: float,
        dti: float,
        safety_buffer_score: float,
    ) -> float:
        return round(
            self._clamp(savings_rate / 2, 0, 10) * 0.25
            + self._clamp(discipline / 10, 0, 10) * 0.20
            + self._clamp(fi_percent / 10, 0, 10) * 0.30
            + safety_buffer_score * 0.15
            + self._clamp((100 - dti) / 10, 0, 10) * 0.10,
            1,
        )

    def _build_fi_score_history(
        self,
        *,
        savings_rate: float,
        discipline: float,
        fi_percent: float,
        dti: float,
        safety_buffer_score: float,
    ) -> dict[str, float]:
        current = round(
            self._clamp(savings_rate / 2, 0, 10) * 0.25
            + self._clamp(discipline / 10, 0, 10) * 0.20
            + self._clamp(fi_percent / 10, 0, 10) * 0.30
            + safety_buffer_score * 0.15
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
        """Р В РІР‚в„ўР В РЎвЂўР В Р’В·Р В Р вЂ Р РЋР вЂљР В Р’В°Р РЋРІР‚В°Р В Р’В°Р В Р’ВµР РЋРІР‚С™ count Р В Р’В·Р В Р’В°Р В Р вЂ Р В Р’ВµР РЋР вЂљР РЋРІвЂљВ¬Р РЋРІР‚ВР В Р вЂ¦Р В Р вЂ¦Р РЋРІР‚в„–Р РЋРІР‚В¦ Р В РЎВР В Р’ВµР РЋР С“Р РЋР РЏР РЋРІР‚В Р В Р’ВµР В Р вЂ  Р Р†Р вЂљРІР‚Сњ Р РЋРІР‚С™Р В Р’ВµР В РЎвЂќР РЋРЎвЂњР РЋРІР‚В°Р В РЎвЂР В РІвЂћвЂ“ Р В РЎВР В Р’ВµР РЋР С“Р РЋР РЏР РЋРІР‚В  Р В Р вЂ¦Р В Р’Вµ Р В Р вЂ Р В РЎвЂќР В Р’В»Р РЋР вЂ№Р РЋРІР‚РЋР В Р’В°Р В Р’ВµР РЋРІР‚С™Р РЋР С“Р РЋР РЏ."""
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
            label=RU_MONTH_LABELS[month - 1],
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

    # ── Large purchases ───────────────────────────────────────────────────────

    def get_large_purchases(
        self,
        user_id: int,
        months: int = 6,
    ) -> dict:
        """Return large and deferred purchases for the last N months.

        Covers two categories of capital-event transactions:
        - is_deferred_purchase=True  — bought on credit/installment; impact
          flows through attribution records when payments are made.
        - is_large_purchase=True     — bought from free cash; excluded from
          the regular expense averages, shown separately.

        Returns a dict with:
            transactions: list[Transaction]  — ordered newest-first
            total_amount: Decimal            — sum of all matched transactions
            months: int                      — lookback window used
        """
        today = date.today()
        start_month = self._shift_month(today, -(months - 1))
        start_dt = datetime(
            start_month.year, start_month.month, 1, tzinfo=timezone.utc
        )

        from sqlalchemy import or_

        txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= start_dt,
                or_(
                    Transaction.is_deferred_purchase.is_(True),
                    Transaction.is_large_purchase.is_(True),
                ),
            )
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .all()
        )

        total_amount = sum(
            (self._to_decimal(tx.amount) for tx in txns), ZERO
        ).quantize(TWOPLACES)

        return {
            "transactions": txns,
            "total_amount": total_amount,
            "months": months,
        }
