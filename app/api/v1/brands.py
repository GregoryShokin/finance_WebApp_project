"""Brand-level endpoints (Brand registry Ph8).

Currently exposes only `POST /brands/{brand_id}/apply-category` —
a per-user category override that also sweeps existing rows of the
brand in active sessions. Used by the «Изменить категорию для всего
бренда» moderator action.

Future Ph8b additions (user-private brand creation) will land here too.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.imports import ApplyBrandCategoryRequest, ApplyBrandCategoryResponse
from app.services.brand_confirm_service import BrandConfirmError, BrandConfirmService

router = APIRouter(prefix="/brands", tags=["Brands"])


@router.post(
    "/{brand_id}/apply-category", response_model=ApplyBrandCategoryResponse,
)
def apply_brand_category(
    brand_id: int,
    payload: ApplyBrandCategoryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set per-user category override for a brand and bulk-apply.

    Effects:
      • Upserts UserBrandCategoryOverride(user, brand → category).
      • Patches normalized_data.category_id for every active-session
        ImportRow whose `brand_id` matches.
      • Future imports of this brand auto-resolve to this category.
    """
    service = BrandConfirmService(db)
    try:
        return service.apply_brand_category_for_user(
            user_id=current_user.id,
            brand_id=brand_id,
            category_id=payload.category_id,
        )
    except BrandConfirmError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
