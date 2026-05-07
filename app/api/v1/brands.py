"""Brand-level endpoints (Brand registry Ph8 + Ph8b).

Surface area:

  POST   /brands                          — create a private brand (Ph8b)
  GET    /brands                          — search/list brands visible to user
  GET    /brands/{id}                     — brand + visible patterns
  POST   /brands/{id}/patterns            — add a private pattern
  POST   /brands/{id}/apply-category      — set per-user category override (Ph8)
  GET    /brands/suggest-from-row         — prefill payload for create form
  GET    /brands/suggested-groups         — «we see N rows like X — create?»

Mutating routes never write `is_global=True` — global brands and global
patterns are maintainer-curated via `scripts/seed_brand_registry.py`.
The API only authors private brands and private (user-scope) patterns.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.brands import (
    BrandCreateRequest,
    BrandDeleteResponse,
    BrandPatternCreateRequest,
    BrandPatternResponse,
    BrandResponse,
    BrandSuggestionResponse,
    BrandUpdateRequest,
    BrandWithPatternsResponse,
    SuggestedBrandGroup,
    SuggestedBrandsResponse,
)
from app.schemas.imports import ApplyBrandCategoryRequest, ApplyBrandCategoryResponse
from app.services.brand_confirm_service import BrandConfirmError, BrandConfirmService
from app.services.brand_management_service import (
    BrandManagementError,
    BrandManagementService,
)

router = APIRouter(prefix="/brands", tags=["Brands"])


# ──────────────────────────────────────────────────────────────────────
# Create
# ──────────────────────────────────────────────────────────────────────


@router.post("", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
def create_brand(
    payload: BrandCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BrandManagementService(db)
    try:
        brand = service.create_private_brand(
            user_id=current_user.id,
            canonical_name=payload.canonical_name,
            category_hint=payload.category_hint,
        )
    except BrandManagementError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    db.commit()
    db.refresh(brand)
    return brand


# ──────────────────────────────────────────────────────────────────────
# List / search / get
# ──────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[BrandResponse])
def list_brands(
    q: str | None = Query(default=None, max_length=64),
    scope: str | None = Query(default=None, pattern="^(private|global)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BrandManagementService(db)
    return service.list_brands_for_picker(
        user_id=current_user.id,
        q=q,
        scope=scope,
        limit=limit,
    )


@router.get("/suggest-from-row", response_model=BrandSuggestionResponse)
def suggest_brand_from_row(
    row_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Prefill the create-brand form from a specific ImportRow.

    Returns empty fields when the row is not visible to the user or has
    no usable signal — caller must still allow a fully-manual create.
    """
    service = BrandManagementService(db)
    canonical, kind, value = service.suggest_from_row(
        user_id=current_user.id, row_id=row_id,
    )
    return BrandSuggestionResponse(
        canonical_name=canonical,
        pattern_kind=kind,
        pattern_value=value,
    )


@router.get("/suggested-groups", response_model=SuggestedBrandsResponse)
def list_suggested_brand_groups(
    session_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Group unresolved rows by extracted brand candidate.

    Drives the «Мы видим N строк, которые выглядят как X — создать бренд?»
    widget in attention-feed. Threshold (≥3 rows) is enforced in service.
    """
    service = BrandManagementService(db)
    suggestions = service.list_unresolved_groups(
        user_id=current_user.id, session_id=session_id,
    )
    return SuggestedBrandsResponse(
        suggestions=[
            SuggestedBrandGroup(
                candidate=s.candidate,
                row_count=s.row_count,
                sample_descriptions=s.sample_descriptions,
                sample_row_ids=s.sample_row_ids,
            )
            for s in suggestions
        ],
    )


@router.get("/{brand_id}", response_model=BrandWithPatternsResponse)
def get_brand(
    brand_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BrandManagementService(db)
    try:
        brand, patterns = service.get_with_patterns(
            user_id=current_user.id, brand_id=brand_id,
        )
    except BrandManagementError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc),
        ) from exc
    return BrandWithPatternsResponse(
        id=brand.id,
        slug=brand.slug,
        canonical_name=brand.canonical_name,
        category_hint=brand.category_hint,
        is_global=brand.is_global,
        created_by_user_id=brand.created_by_user_id,
        patterns=[BrandPatternResponse.model_validate(p) for p in patterns],
    )


# ──────────────────────────────────────────────────────────────────────
# Update / Delete (private brands only)
# ──────────────────────────────────────────────────────────────────────


@router.patch("/{brand_id}", response_model=BrandResponse)
def update_brand(
    brand_id: int,
    payload: BrandUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename / re-hint a private brand. Global brands are read-only."""
    service = BrandManagementService(db)
    try:
        brand = service.update_private_brand(
            user_id=current_user.id,
            brand_id=brand_id,
            canonical_name=payload.canonical_name,
            category_hint=payload.category_hint,
        )
    except BrandManagementError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    db.commit()
    db.refresh(brand)
    return brand


@router.delete("/{brand_id}", response_model=BrandDeleteResponse)
def delete_brand(
    brand_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a private brand + clear its traces from ImportRows."""
    service = BrandManagementService(db)
    try:
        rows_cleared = service.delete_private_brand(
            user_id=current_user.id, brand_id=brand_id,
        )
    except BrandManagementError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    db.commit()
    return BrandDeleteResponse(brand_id=brand_id, rows_cleared=rows_cleared)


# ──────────────────────────────────────────────────────────────────────
# Patterns
# ──────────────────────────────────────────────────────────────────────


@router.post(
    "/{brand_id}/patterns",
    response_model=BrandPatternResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_brand_pattern(
    brand_id: int,
    payload: BrandPatternCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = BrandManagementService(db)
    try:
        bp, _is_new = service.add_pattern_to_brand(
            user_id=current_user.id,
            brand_id=brand_id,
            kind=payload.kind,
            pattern=payload.pattern,
            is_regex=payload.is_regex,
        )
    except BrandManagementError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc
    db.commit()
    db.refresh(bp)
    return bp


# ──────────────────────────────────────────────────────────────────────
# Apply brand to a whole session (post-create bulk-confirm)
# ──────────────────────────────────────────────────────────────────────


@router.post("/{brand_id}/apply-to-session")
def apply_brand_to_session(
    brand_id: int,
    session_id: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-resolve unresolved rows in a session against the brand's pattern set
    and confirm matches. Used right after «+ Создать бренд» so a freshly-added
    pattern auto-applies to the rest of the active session.

    Returns counters: matched / confirmed / skipped_user_decision /
    skipped_already_resolved.
    """
    service = BrandManagementService(db)
    try:
        return service.apply_brand_to_session(
            user_id=current_user.id,
            brand_id=brand_id,
            session_id=session_id,
        )
    except BrandManagementError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc),
        ) from exc


# ──────────────────────────────────────────────────────────────────────
# Apply category (Ph8 — was already here, kept verbatim)
# ──────────────────────────────────────────────────────────────────────


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
