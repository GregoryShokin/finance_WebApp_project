from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.imports import (
    ImportCommitRequest,
    ImportCommitResponse,
    ImportMappingRequest,
    ImportPreviewResponse,
    ImportSessionListResponse,
    ImportReviewQueueResponse,
    ImportRowLabelRequest,
    ImportRowLabelResponse,
    ImportRowUpdateRequest,
    ImportRowUpdateResponse,
    ImportSessionResponse,
    ImportUploadResponse,
)
from app.services.import_service import ImportNotFoundError, ImportService, ImportValidationError

router = APIRouter(prefix="/imports", tags=["Imports"])


@router.get("/review-queue", response_model=ImportReviewQueueResponse)
def get_import_review_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    return service.list_review_queue(user_id=current_user.id)


@router.get("/sessions", response_model=ImportSessionListResponse)
def list_import_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Список незавершённых сессий импорта текущего пользователя."""
    service = ImportService(db)
    return service.list_active_sessions(user_id=current_user.id)


@router.post("/upload", response_model=ImportUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_import_file(
    file: UploadFile = File(...),
    delimiter: str = ",",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        raw_bytes = await file.read()
        return service.upload_source(
            user_id=current_user.id,
            filename=file.filename or "import_file",
            raw_bytes=raw_bytes,
            delimiter=delimiter,
        )
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc





@router.post("/rows/{row_id}/label", response_model=ImportRowLabelResponse)
def set_import_row_label(
    row_id: int,
    payload: ImportRowLabelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.set_row_label(user_id=current_user.id, row_id=row_id, user_label=payload.user_label)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/rows/{row_id}", response_model=ImportRowUpdateResponse)
def update_import_row(
    row_id: int,
    payload: ImportRowUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.update_row(user_id=current_user.id, row_id=row_id, payload=payload)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{session_id}", response_model=ImportSessionResponse)
def get_import_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.get_session(user_id=current_user.id, session_id=session_id)
    except ImportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_import_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        service.delete_session(user_id=current_user.id, session_id=session_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{session_id}/preview", response_model=ImportPreviewResponse)
def get_import_preview(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.get_existing_preview(user_id=current_user.id, session_id=session_id)
    except ImportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{session_id}/preview", response_model=ImportPreviewResponse)
def preview_import(
    session_id: int,
    payload: ImportMappingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.build_preview(user_id=current_user.id, session_id=session_id, payload=payload)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{session_id}/commit", response_model=ImportCommitResponse)
def commit_import(
    session_id: int,
    payload: ImportCommitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.commit_import(
            user_id=current_user.id,
            session_id=session_id,
            import_ready_only=payload.import_ready_only,
        )
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
