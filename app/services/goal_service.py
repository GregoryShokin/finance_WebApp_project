from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.goal import Goal, GoalStatus, GoalSystemKey
from app.models.transaction import Transaction


class GoalNotFoundError(Exception):
    pass


class GoalValidationError(Exception):
    pass


_UNSET = object()
_MAX_MONTHS = 6
_SAFETY_BUFFER_NAME = "Подушка безопасности"
_SAFETY_BUFFER_MONTHS = Decimal("5")
_ZERO = Decimal("0.00")


@dataclass
class GoalProgress:
    goal: Goal
    saved: Decimal
    percent: float
    remaining: Decimal
    monthly_needed: Decimal | None
    is_on_track: bool | None = None
    shortfall: Decimal | None = None
    estimated_date: date | None = None


def _months_between(d_from: date, d_to: date) -> int:
    """
    Количество полных месяцев от d_from до d_to.
    Если d_to.day >= d_from.day — месяц считается полным.
    Пример: 6 апреля -> 7 декабря = 8 месяцев.
    Пример: 6 апреля -> 5 декабря = 7 месяцев.
    """
    months = (d_to.year - d_from.year) * 12 + (d_to.month - d_from.month)
    if d_to.day < d_from.day:
        months -= 1
    return max(months, 0)


def _start_of_month(value: date | datetime) -> date:
    return date(value.year, value.month, 1)


def _shift_month(base: date, offset: int) -> date:
    year = base.year + (base.month - 1 + offset) // 12
    month = (base.month - 1 + offset) % 12 + 1
    return date(year, month, 1)


def _month_key(value: date | datetime) -> str:
    return f"{value.year}-{value.month:02d}"


def _to_money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class GoalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_goal(self, goal_id: int, user_id: int) -> Goal:
        goal = self.db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user_id).first()
        if goal is None:
            raise GoalNotFoundError("Цель не найдена")
        return goal

    def _get_system_goal(self, user_id: int, system_key: GoalSystemKey) -> Goal | None:
        return self.db.query(Goal).filter(Goal.user_id == user_id, Goal.system_key == system_key.value).first()

    def _compute_saved(self, goal_id: int) -> Decimal:
        result = (
            self.db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0")))
            .filter(Transaction.goal_id == goal_id)
            .scalar()
        )
        return _to_money(result)

    def _compute_avg_monthly_expenses(self, user_id: int) -> Decimal:
        expenses = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.affects_analytics.is_(True),
            )
            .order_by(Transaction.transaction_date.asc())
            .all()
        )

        if not expenses:
            return _ZERO

        current_month = _start_of_month(date.today())
        first_expense_month = _start_of_month(expenses[0].transaction_date.date())
        candidate_start_month = _shift_month(current_month, -(_MAX_MONTHS - 1))
        start_month = first_expense_month if first_expense_month > candidate_start_month else candidate_start_month

        included_month_keys: set[str] = set()
        cursor = start_month
        while cursor <= current_month:
            included_month_keys.add(_month_key(cursor))
            cursor = _shift_month(cursor, 1)

        months_used = len(included_month_keys)
        if months_used == 0:
            return _ZERO

        total_expense = Decimal("0")
        for transaction in expenses:
            if _month_key(transaction.transaction_date.date()) not in included_month_keys:
                continue
            total_expense += Decimal(str(transaction.amount or 0))

        return _to_money(total_expense / Decimal(str(months_used)))

    def _compute_monthly_avg_balance(self, user_id: int) -> Decimal:
        today = date.today()
        current_month_start = date(today.year, today.month, 1)
        rows = (
            self.db.query(
                func.date_trunc("month", Transaction.transaction_date).label("month"),
                func.sum(
                    case(
                        (Transaction.type == "income", Transaction.amount),
                        else_=-Transaction.amount,
                    )
                ).label("balance"),
            )
            .filter(
                Transaction.user_id == user_id,
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date < current_month_start,
            )
            .group_by(func.date_trunc("month", Transaction.transaction_date))
            .order_by(func.date_trunc("month", Transaction.transaction_date).desc())
            .limit(6)
            .all()
        )
        if not rows:
            return Decimal("0")
        total = sum((Decimal(str(row.balance)) for row in rows), Decimal("0"))
        return _to_money(total / Decimal(str(len(rows))))

    def _sync_safety_buffer_goal(self, user_id: int) -> Goal:
        avg_monthly_expenses = self._compute_avg_monthly_expenses(user_id)
        target_amount = _to_money(avg_monthly_expenses * _SAFETY_BUFFER_MONTHS) if avg_monthly_expenses > 0 else _ZERO

        goal = self._get_system_goal(user_id, GoalSystemKey.safety_buffer)
        if goal is None:
            goal = Goal(
                user_id=user_id,
                name=_SAFETY_BUFFER_NAME,
                target_amount=target_amount,
                deadline=None,
                status=GoalStatus.active.value,
                is_system=True,
                system_key=GoalSystemKey.safety_buffer.value,
            )
            self.db.add(goal)
            self.db.commit()
            self.db.refresh(goal)
            return goal

        changed = False
        if goal.name != _SAFETY_BUFFER_NAME:
            goal.name = _SAFETY_BUFFER_NAME
            changed = True
        if not goal.is_system:
            goal.is_system = True
            changed = True
        if goal.system_key != GoalSystemKey.safety_buffer.value:
            goal.system_key = GoalSystemKey.safety_buffer.value
            changed = True
        if _to_money(goal.target_amount) != target_amount:
            goal.target_amount = target_amount
            changed = True

        saved = self._compute_saved(goal.id)
        desired_status = GoalStatus.active.value
        if target_amount > 0 and saved >= target_amount:
            desired_status = GoalStatus.achieved.value
        if goal.status != desired_status:
            goal.status = desired_status
            changed = True

        if changed:
            self.db.add(goal)
            self.db.commit()
            self.db.refresh(goal)

        return goal

    def ensure_system_goals(self, user_id: int) -> None:
        self._sync_safety_buffer_goal(user_id)

    def _build_progress(self, goal: Goal) -> GoalProgress:
        saved = self._compute_saved(goal.id)
        target = Decimal(str(goal.target_amount))

        if target > 0:
            pct = float(min(saved / target * 100, Decimal("100")))
        else:
            pct = 0.0

        remaining = max(target - saved, Decimal("0"))

        monthly_needed: Decimal | None = None
        if goal.deadline is not None and remaining > 0:
            months = _months_between(date.today(), goal.deadline)
            if months > 0:
                monthly_needed = _to_money(remaining / Decimal(str(months)))

        smo = self._compute_monthly_avg_balance(goal.user_id)
        is_on_track: bool | None = None
        shortfall: Decimal | None = None
        estimated_date: date | None = None

        if smo > 0 and remaining > 0:
            months_needed = int(
                (remaining / smo).to_integral_value(rounding=ROUND_HALF_UP)
            )
            estimated_date = _shift_month(date.today(), months_needed)

        if monthly_needed is not None and smo > 0:
            is_on_track = smo >= monthly_needed
            if not is_on_track:
                shortfall = _to_money(monthly_needed - smo)

        return GoalProgress(
            goal=goal,
            saved=_to_money(saved),
            percent=round(pct, 1),
            remaining=_to_money(remaining),
            monthly_needed=monthly_needed,
            is_on_track=is_on_track,
            shortfall=shortfall,
            estimated_date=estimated_date,
        )

    def compute_forecast(
        self,
        *,
        user_id: int,
        target_amount: Decimal,
        deadline: date | None,
        monthly_contribution: Decimal | None,
    ) -> dict:
        smo = self._compute_monthly_avg_balance(user_id)
        contribution = monthly_contribution if monthly_contribution is not None else smo

        monthly_needed: Decimal | None = None
        is_achievable = True
        shortfall: Decimal | None = None
        estimated_months: int | None = None
        estimated_date: date | None = None
        suggested_date: date | None = None
        contribution_percent: Decimal | None = None
        deadline_too_close = False

        if smo > 0:
            contribution_percent = _to_money(contribution / smo * 100)

        if contribution > 0:
            months_needed = math.ceil(float(target_amount / contribution))
            estimated_months = months_needed
            estimated_date = _shift_month(date.today(), months_needed)

        if deadline is not None:
            months_to_deadline = _months_between(date.today(), deadline)
            if months_to_deadline == 0:
                return {
                    "monthly_avg_balance": _to_money(smo),
                    "monthly_needed": None,
                    "estimated_months": estimated_months,
                    "estimated_date": estimated_date,
                    "is_achievable": False,
                    "shortfall": _to_money(target_amount),
                    "suggested_date": estimated_date,
                    "contribution_percent": contribution_percent,
                    "deadline_too_close": True,
                }

            monthly_needed = _to_money(target_amount / Decimal(str(months_to_deadline)))

        if deadline is not None and estimated_date is not None:
            is_achievable = estimated_date <= deadline
            if is_achievable:
                suggested_date = None
                shortfall = None
            else:
                shortfall = (
                    _to_money(monthly_needed - contribution)
                    if monthly_needed is not None
                    else None
                )
                suggested_date = estimated_date

        return {
            "monthly_avg_balance": _to_money(smo),
            "monthly_needed": monthly_needed,
            "estimated_months": estimated_months,
            "estimated_date": estimated_date,
            "is_achievable": is_achievable,
            "shortfall": shortfall,
            "suggested_date": suggested_date,
            "contribution_percent": contribution_percent,
            "deadline_too_close": deadline_too_close,
        }

    def create_goal(
        self,
        *,
        user_id: int,
        name: str,
        target_amount: Decimal,
        deadline: date | None,
    ) -> Goal:
        goal = Goal(
            user_id=user_id,
            name=name,
            target_amount=target_amount,
            deadline=deadline,
            status=GoalStatus.active.value,
            is_system=False,
            system_key=None,
        )
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def get_goals(self, user_id: int) -> list[GoalProgress]:
        self.ensure_system_goals(user_id)
        goals = self.db.query(Goal).filter(Goal.user_id == user_id).order_by(Goal.created_at.desc()).all()
        return [self._build_progress(goal) for goal in goals]

    def get_goal_by_id(self, goal_id: int, user_id: int) -> GoalProgress:
        self.ensure_system_goals(user_id)
        goal = self._get_goal(goal_id, user_id)
        return self._build_progress(goal)

    def update_goal(
        self,
        *,
        goal_id: int,
        user_id: int,
        name: str | None = None,
        target_amount: Decimal | None = None,
        deadline: date | None | object = _UNSET,
    ) -> Goal:
        goal = self._get_goal(goal_id, user_id)
        if goal.is_system:
            raise GoalValidationError("Системную цель нельзя редактировать вручную")
        if goal.status == GoalStatus.archived.value:
            raise GoalValidationError("Нельзя редактировать архивную цель")

        if name is not None:
            goal.name = name
        if target_amount is not None:
            goal.target_amount = target_amount
        if deadline is not _UNSET:
            goal.deadline = deadline

        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def archive_goal(self, goal_id: int, user_id: int) -> Goal:
        goal = self._get_goal(goal_id, user_id)
        if goal.is_system:
            raise GoalValidationError("Системную цель нельзя архивировать")
        goal.status = GoalStatus.archived.value
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def check_and_achieve(self, goal_id: int, user_id: int) -> None:
        try:
            goal = self._get_goal(goal_id, user_id)
        except GoalNotFoundError:
            return

        if goal.status != GoalStatus.active.value:
            return

        saved = self._compute_saved(goal_id)
        target = Decimal(str(goal.target_amount))
        if target > 0 and saved >= target:
            goal.status = GoalStatus.achieved.value
            self.db.add(goal)

    def validate_goal_for_transaction(self, goal_id: int, user_id: int) -> None:
        goal = self.db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user_id).first()
        if goal is None:
            raise GoalValidationError("Цель не найдена")
        if goal.status not in {GoalStatus.active.value, GoalStatus.achieved.value}:
            raise GoalValidationError("Можно привязывать транзакции только к активным целям")
