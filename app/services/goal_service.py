from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.goal import Goal, GoalStatus
from app.models.transaction import Transaction


class GoalNotFoundError(Exception):
    pass


class GoalValidationError(Exception):
    pass


_UNSET = object()  # sentinel for "field not provided in update"


@dataclass
class GoalProgress:
    goal: Goal
    saved: Decimal
    percent: float
    remaining: Decimal
    monthly_needed: Decimal | None


def _months_between(d_from: date, d_to: date) -> int:
    """Positive integer of months from d_from to d_to; 0 if d_to <= d_from."""
    months = (d_to.year - d_from.year) * 12 + (d_to.month - d_from.month)
    return max(months, 0)


class GoalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_goal(self, goal_id: int, user_id: int) -> Goal:
        goal = (
            self.db.query(Goal)
            .filter(Goal.id == goal_id, Goal.user_id == user_id)
            .first()
        )
        if goal is None:
            raise GoalNotFoundError("Цель не найдена")
        return goal

    def _compute_saved(self, goal_id: int) -> Decimal:
        result = (
            self.db.query(func.coalesce(func.sum(Transaction.amount), Decimal("0")))
            .filter(Transaction.goal_id == goal_id)
            .scalar()
        )
        return Decimal(str(result))

    def _build_progress(self, goal: Goal) -> GoalProgress:
        saved = self._compute_saved(goal.id)
        target = Decimal(str(goal.target_amount))

        if target > 0:
            pct = float(min(saved / target * 100, Decimal("100")))
        else:
            pct = 100.0

        remaining = max(target - saved, Decimal("0"))

        monthly_needed: Decimal | None = None
        if goal.deadline is not None and remaining > 0:
            months = _months_between(date.today(), goal.deadline)
            if months > 0:
                monthly_needed = (remaining / Decimal(str(months))).quantize(Decimal("0.01"))

        return GoalProgress(
            goal=goal,
            saved=saved.quantize(Decimal("0.01")),
            percent=round(pct, 1),
            remaining=remaining.quantize(Decimal("0.01")),
            monthly_needed=monthly_needed,
        )

    # ── public API ────────────────────────────────────────────────────────────

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
        )
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def get_goals(self, user_id: int) -> list[GoalProgress]:
        goals = (
            self.db.query(Goal)
            .filter(Goal.user_id == user_id)
            .order_by(Goal.created_at.desc())
            .all()
        )
        return [self._build_progress(g) for g in goals]

    def get_goal_by_id(self, goal_id: int, user_id: int) -> GoalProgress:
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
        if goal.status == GoalStatus.archived.value:
            raise GoalValidationError("Нельзя редактировать архивную цель")

        if name is not None:
            goal.name = name
        if target_amount is not None:
            goal.target_amount = target_amount
        if deadline is not _UNSET:
            goal.deadline = deadline  # type: ignore[assignment]

        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def archive_goal(self, goal_id: int, user_id: int) -> Goal:
        goal = self._get_goal(goal_id, user_id)
        goal.status = GoalStatus.archived.value
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def check_and_achieve(self, goal_id: int, user_id: int) -> None:
        """Автоматически переводит цель в 'achieved' если накопленная сумма >= цели."""
        try:
            goal = self._get_goal(goal_id, user_id)
        except GoalNotFoundError:
            return

        if goal.status != GoalStatus.active.value:
            return

        saved = self._compute_saved(goal_id)
        if saved >= Decimal(str(goal.target_amount)):
            goal.status = GoalStatus.achieved.value
            self.db.add(goal)
            # Caller is responsible for commit

    def validate_goal_for_transaction(self, goal_id: int, user_id: int) -> None:
        """Проверяет что цель принадлежит пользователю и активна."""
        goal = (
            self.db.query(Goal)
            .filter(Goal.id == goal_id, Goal.user_id == user_id)
            .first()
        )
        if goal is None:
            raise GoalValidationError("Цель не найдена")
        if goal.status != GoalStatus.active.value:
            raise GoalValidationError("Можно привязывать транзакции только к активным целям")
