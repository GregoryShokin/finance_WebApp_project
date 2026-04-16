from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.school_moment import SchoolMomentResponse, SchoolMomentsListResponse
from app.services.school_moments_service import SchoolMomentsService

router = APIRouter(prefix="/school", tags=["School"])


@router.get("/moments", response_model=SchoolMomentsListResponse)
def get_school_moments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns educational financial moments/tips based on user metrics."""
    svc = SchoolMomentsService(db)
    moments = svc.get_school_moments(current_user.id)
    return SchoolMomentsListResponse(
        moments=[SchoolMomentResponse(**m) for m in moments],
    )
