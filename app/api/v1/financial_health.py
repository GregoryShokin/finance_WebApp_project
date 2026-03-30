from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models.real_asset import RealAsset
from app.models.user import User
from app.schemas.financial_health import (
    DebtRatioInfo,
    FinancialHealthResponse,
    RealAssetCreate,
    RealAssetResponse,
    RealAssetUpdate,
)
from app.services.financial_health_service import FinancialHealthService

router = APIRouter(tags=["Financial Health"])


# ── GET /financial-health ─────────────────────────────────────────────────────

@router.get("/financial-health", response_model=FinancialHealthResponse)
def get_financial_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = FinancialHealthService(db)

    dti = svc.get_dti(current_user.id)
    basic = svc.get_debt_ratio(current_user.id, include_real_assets=False)

    has_real_assets = (
        db.query(RealAsset)
        .filter(RealAsset.user_id == current_user.id)
        .first()
    ) is not None

    extended: DebtRatioInfo | None = None
    if has_real_assets:
        ext = svc.get_debt_ratio(current_user.id, include_real_assets=True)
        extended = DebtRatioInfo(
            value=ext.debt_ratio_percent,
            status=ext.status,
            total_debt=ext.total_debt,
            total_assets=ext.total_assets,
        )

    return FinancialHealthResponse(
        dti_value=dti.dti_percent,
        dti_status=dti.status,
        debt_ratio_basic=DebtRatioInfo(
            value=basic.debt_ratio_percent,
            status=basic.status,
            total_debt=basic.total_debt,
            total_assets=basic.total_assets,
        ),
        debt_ratio_extended=extended,
    )


# ── GET /real-assets ──────────────────────────────────────────────────────────

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


# ── POST /real-assets ─────────────────────────────────────────────────────────

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
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# ── PUT /real-assets/{id} ─────────────────────────────────────────────────────

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


# ── DELETE /real-assets/{id} ──────────────────────────────────────────────────

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
