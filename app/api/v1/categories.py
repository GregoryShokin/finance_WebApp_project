
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.category import (
    CategoryCreateRequest,
    CategoryKind,
    CategoryPriority,
    CategoryResponse,
    CategoryUpdateRequest,
)
from app.services.category_service import CategoryNotFoundError, CategoryService, CategoryValidationError

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("", response_model=list[CategoryResponse])
def list_categories(
    kind: CategoryKind | None = Query(default=None),
    priority: CategoryPriority | None = Query(default=None),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CategoryService(db)
    return service.list_categories(
        user_id=current_user.id,
        kind=kind.value if kind else None,
        priority=priority.value if priority else None,
        search=search,
    )


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CategoryService(db)
    try:
        return service.create_category(
            user_id=current_user.id,
            name=payload.name,
            kind=payload.kind.value,
            priority=payload.priority.value,
            color=payload.color,
            is_system=payload.is_system,
        )
    except CategoryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.put("/{category_id}", response_model=CategoryResponse)
def update_category(
    category_id: int,
    payload: CategoryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CategoryService(db)
    updates = payload.model_dump(exclude_unset=True)
    if "kind" in updates and updates["kind"] is not None:
        updates["kind"] = updates["kind"].value
    if "priority" in updates and updates["priority"] is not None:
        updates["priority"] = updates["priority"].value

    try:
        return service.update_category(user_id=current_user.id, category_id=category_id, updates=updates)
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CategoryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = CategoryService(db)
    try:
        service.delete_category(user_id=current_user.id, category_id=category_id)
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
