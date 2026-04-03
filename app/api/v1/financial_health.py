from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.real_asset import RealAsset
from app.models.user import User
from app.schemas.financial_health import FinancialHealthResponse, RealAssetCreate, RealAssetResponse, RealAssetUpdate
from app.services.financial_health_service import FinancialHealthService

router = APIRouter(tags=["Financial Health"])


@router.get("/financial-health", response_model=FinancialHealthResponse)
def get_financial_health_current(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return FinancialHealthService(db).get_financial_health(current_user.id)


@router.get("/financial-health/{user_id}", response_model=FinancialHealthResponse)
def get_financial_health_by_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return FinancialHealthService(db).get_financial_health(user_id)


@router.get("/real-assets", response_model=list[RealAssetResponse])
def list_real_assets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(RealAsset)
        .filter(RealAsset.user_id == current_user.id)
        .order_by(RealAsset.id)
        .all()
    )


@router.post("/real-assets", response_model=RealAssetResponse, status_code=status.HTTP_201_CREATED)
def create_real_asset(
    payload: RealAssetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = RealAsset(
        user_id=current_user.id,
        asset_type=payload.asset_type,
        name=payload.name,
        estimated_value=payload.estimated_value,
        linked_account_id=payload.linked_account_id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.put("/real-assets/{asset_id}", response_model=RealAssetResponse)
def update_real_asset(
    asset_id: int,
    payload: RealAssetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(RealAsset).filter(
        RealAsset.id == asset_id,
        RealAsset.user_id == current_user.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(asset, field, value)

    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/real-assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_real_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.query(RealAsset).filter(
        RealAsset.id == asset_id,
        RealAsset.user_id == current_user.id,
    ).first()
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    db.delete(asset)
    db.commit()