from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.goal import (
    GoalCreateRequest,
    GoalForecastResponse,
    GoalResponse,
    GoalUpdateRequest,
    GoalWithProgressResponse,
)
from app.services.goal_service import GoalNotFoundError, GoalService, GoalValidationError

router = APIRouter(prefix="/goals", tags=["Goals"])


def _to_progress_response(progress) -> GoalWithProgressResponse:
    return GoalWithProgressResponse(
        id=progress.goal.id,
        user_id=progress.goal.user_id,
        name=progress.goal.name,
        target_amount=progress.goal.target_amount,
        deadline=progress.goal.deadline,
        status=progress.goal.status,
        is_system=progress.goal.is_system,
        system_key=progress.goal.system_key,
        created_at=progress.goal.created_at,
        updated_at=progress.goal.updated_at,
        saved=progress.saved,
        percent=progress.percent,
        remaining=progress.remaining,
        monthly_needed=progress.monthly_needed,
        is_on_track=progress.is_on_track,
        shortfall=progress.shortfall,
        estimated_date=progress.estimated_date,
    )


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = GoalService(db)
    goal = service.create_goal(
        user_id=current_user.id,
        name=payload.name,
        target_amount=payload.target_amount,
        deadline=payload.deadline,
    )
    return goal


@router.get("", response_model=list[GoalWithProgressResponse])
def list_goals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = GoalService(db)
    return [_to_progress_response(progress) for progress in service.get_goals(current_user.id)]


@router.get("/forecast", response_model=GoalForecastResponse)
def get_goal_forecast(
    target_amount: Decimal = Query(..., gt=0),
    deadline: date | None = Query(default=None),
    monthly_contribution: Decimal | None = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = GoalService(db)
    result = svc.compute_forecast(
        user_id=current_user.id,
        target_amount=target_amount,
        deadline=deadline,
        monthly_contribution=monthly_contribution,
    )
    return GoalForecastResponse(**result)


@router.get("/{goal_id}", response_model=GoalWithProgressResponse)
def get_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = GoalService(db)
    try:
        return _to_progress_response(service.get_goal_by_id(goal_id, current_user.id))
    except GoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: int,
    payload: GoalUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = GoalService(db)
    data = payload.model_dump(exclude_unset=True)
    from app.services.goal_service import _UNSET

    try:
        goal = service.update_goal(
            goal_id=goal_id,
            user_id=current_user.id,
            name=data.get("name"),
            target_amount=data.get("target_amount"),
            deadline=data["deadline"] if "deadline" in data else _UNSET,
        )
        return goal
    except GoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoalValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{goal_id}/archive", response_model=GoalResponse)
def archive_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = GoalService(db)
    try:
        return service.archive_goal(goal_id, current_user.id)
    except GoalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GoalValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
