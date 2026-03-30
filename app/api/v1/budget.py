from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.budget import Budget
from app.models.budget_alert import BudgetAlert
from app.models.user import User
from app.schemas.budget import BudgetAlertResponse, BudgetProgressResponse, BudgetUpdateRequest
from app.services.budget_analytics_service import BudgetAnalyticsService

router = APIRouter(prefix="/budget", tags=["Budget"])


# ── GET /budget/alerts — must come BEFORE /budget/{month} ────────────────────

@router.get("/alerts", response_model=list[BudgetAlertResponse])
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns unread budget alerts for the current user."""
    return (
        db.query(BudgetAlert)
        .filter(
            BudgetAlert.user_id == current_user.id,
            BudgetAlert.is_read.is_(False),
        )
        .order_by(BudgetAlert.triggered_at.desc())
        .all()
    )


# ── POST /budget/alerts/{id}/read ─────────────────────────────────────────────

@router.post("/alerts/{alert_id}/read", response_model=BudgetAlertResponse)
def mark_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marks a budget alert as read."""
    alert = db.query(BudgetAlert).filter(
        BudgetAlert.id == alert_id,
        BudgetAlert.user_id == current_user.id,
    ).first()
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return alert


# ── GET /budget/{month} ───────────────────────────────────────────────────────

@router.get("/{month}", response_model=list[BudgetProgressResponse])
def get_budget_progress(
    month: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns budget progress for the given month (YYYY-MM-DD or YYYY-MM-01).
    Auto-generates budget records if none exist for the month yet.
    """
    svc = BudgetAnalyticsService(db)
    first = month.replace(day=1)

    # Auto-generate if no budgets for this month yet
    existing = db.query(Budget).filter(
        Budget.user_id == current_user.id,
        Budget.month == first,
    ).first()
    if not existing:
        svc.generate_budget_for_month(current_user.id, first)

    items = svc.get_budget_progress(current_user.id, first)
    return [
        BudgetProgressResponse(
            category_id=i.category_id,
            category_name=i.category_name,
            planned_amount=i.planned_amount,
            spent_amount=i.spent_amount,
            remaining=i.remaining,
            percent_used=i.percent_used,
        )
        for i in items
    ]


# ── PUT /budget/{month}/{category_id} ────────────────────────────────────────

@router.put("/{month}/{category_id}", response_model=BudgetProgressResponse)
def update_budget(
    month: date,
    category_id: int,
    payload: BudgetUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Updates the planned_amount for a budget entry and marks it as manual."""
    first = month.replace(day=1)
    budget = db.query(Budget).filter(
        Budget.user_id == current_user.id,
        Budget.category_id == category_id,
        Budget.month == first,
    ).first()

    if not budget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget entry not found")

    budget.planned_amount = payload.planned_amount
    budget.auto_generated = False
    db.commit()
    db.refresh(budget)

    # Return fresh progress item for this category
    svc = BudgetAnalyticsService(db)
    items = svc.get_budget_progress(current_user.id, first)
    for item in items:
        if item.category_id == category_id:
            return BudgetProgressResponse(
                category_id=item.category_id,
                category_name=item.category_name,
                planned_amount=item.planned_amount,
                spent_amount=item.spent_amount,
                remaining=item.remaining,
                percent_used=item.percent_used,
            )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget entry not found after update")
