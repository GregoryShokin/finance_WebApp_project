from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.user_settings import UserSettingsResponse, UserSettingsUpdateRequest
from app.services.user_settings_service import UserSettingsService, UserSettingsValidationError

router = APIRouter(prefix="/users/settings", tags=["User Settings"])


@router.get("", response_model=UserSettingsResponse)
def get_user_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current user's settings (returns defaults if not yet saved)."""
    service = UserSettingsService(db)
    row = service.get_or_default(current_user.id)
    return UserSettingsResponse(
        user_id=row.user_id,
        large_purchase_threshold_pct=float(row.large_purchase_threshold_pct),
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


@router.patch("", response_model=UserSettingsResponse)
def update_user_settings(
    payload: UserSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the large-purchase threshold percentage."""
    service = UserSettingsService(db)
    try:
        row = service.update(
            user_id=current_user.id,
            large_purchase_threshold_pct=payload.large_purchase_threshold_pct,
        )
        db.commit()
        db.refresh(row)
    except UserSettingsValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return UserSettingsResponse(
        user_id=row.user_id,
        large_purchase_threshold_pct=float(row.large_purchase_threshold_pct),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
