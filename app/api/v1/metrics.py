from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.metrics import (
    CapitalMetricResponse,
    DTIMetricResponse,
    FinancialIndependenceMetricResponse,
    FlowMetricResponse,
    HealthRecommendation,
    HealthSummaryResponse,
    MetricsResponse,
    MetricsSummaryResponse,
    ReserveMetricResponse,
    SavingsRateMetricResponse,
)
from app.services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(
    month: str = Query(..., description="Month in YYYY-MM format, e.g. 2026-03"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns financial independence and savings rate metrics for the given month.

    financial_independence may be null when there are no expense data
    for any of the last 3 completed months.
    """
    try:
        current_month = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid month format. Use YYYY-MM (e.g. 2026-03).",
        )

    svc = MetricsService(db)

    fi = svc.get_financial_independence(current_user.id, current_month)
    sr = svc.get_savings_rate(current_user.id, current_month)

    return MetricsResponse(
        financial_independence=(
            FinancialIndependenceMetricResponse(
                percent=fi.percent,
                passive_income=fi.passive_income,
                avg_expenses=fi.avg_expenses,
                gap=fi.gap,
                months_of_data=fi.months_of_data,
            )
            if fi is not None
            else None
        ),
        savings_rate=SavingsRateMetricResponse(
            percent=sr.percent,
            invested=sr.invested,
            total_income=sr.total_income,
        ),
    )


@router.get("/summary", response_model=MetricsSummaryResponse)
def get_metrics_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns all four metrics (Flow, Capital, DTI, Reserve) plus FI-score."""
    svc = MetricsService(db)
    data = svc.calculate_metrics_summary(current_user.id)
    return MetricsSummaryResponse(
        flow=FlowMetricResponse(**data["flow"]),
        capital=CapitalMetricResponse(**data["capital"]),
        dti=DTIMetricResponse(**data["dti"]),
        reserve=ReserveMetricResponse(**data["reserve"]),
        fi_score=data["fi_score"],
    )


@router.get("/health", response_model=HealthSummaryResponse)
def get_health_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns health summary with metrics, FI-score, weakest metric, and recommendations."""
    svc = MetricsService(db)
    data = svc.calculate_health_summary(current_user.id)
    metrics = data["metrics"]
    return HealthSummaryResponse(
        metrics=MetricsSummaryResponse(
            flow=FlowMetricResponse(**metrics["flow"]),
            capital=CapitalMetricResponse(**metrics["capital"]),
            dti=DTIMetricResponse(**metrics["dti"]),
            reserve=ReserveMetricResponse(**metrics["reserve"]),
            fi_score=metrics["fi_score"],
        ),
        fi_score=data["fi_score"],
        fi_zone=data["fi_zone"],
        weakest_metric=data["weakest_metric"],
        recommendations=[HealthRecommendation(**r) for r in data["recommendations"]],
    )
