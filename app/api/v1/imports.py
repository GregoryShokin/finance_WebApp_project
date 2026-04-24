from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.imports import (
    AttachRowToClusterRequest,
    AttachRowToClusterResponse,
    BulkApplyRequest,
    BulkApplyResponse,
    BulkClustersResponse,
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





@router.get("/{session_id}/moderation-status")
def get_moderation_status(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.get_moderation_status(user_id=current_user.id, session_id=session_id)
    except ImportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{session_id}/moderate")
def start_moderation(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.start_moderation(user_id=current_user.id, session_id=session_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/moderation-metrics")
def get_moderation_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregate moderator metrics across the user's sessions (Phase 6.1)."""
    from app.services.moderation_metrics_service import ModerationMetricsService

    metrics = ModerationMetricsService(db).compute_for_user(user_id=current_user.id)
    return metrics.to_dict()


@router.post("/rematch-transfers")
def rematch_transfers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-run the global transfer matcher across all user sessions.

    Use when sessions were uploaded/removed and cross-session pairs may have
    shifted. Cheap — pure DB work, no LLM. Goes through the debounced matcher
    so manual + automatic triggers coalesce into a single run.
    """
    from app.jobs.transfer_matcher_debounced import schedule_transfer_match

    schedule_transfer_match(current_user.id)
    return {"status": "queued"}


@router.get("/parked-queue")
def get_parked_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    return service.list_parked_queue(user_id=current_user.id)


@router.post("/rows/{row_id}/park")
def park_import_row(
    row_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.park_row(user_id=current_user.id, row_id=row_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/rows/{row_id}/unpark")
def unpark_import_row(
    row_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.unpark_row(user_id=current_user.id, row_id=row_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/rows/{row_id}/exclude")
def exclude_import_row(
    row_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.exclude_row(user_id=current_user.id, row_id=row_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/rows/{row_id}/unexclude")
def unexclude_import_row(
    row_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.unexclude_row(user_id=current_user.id, row_id=row_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/rows/{row_id}/detach-from-cluster")
def detach_row_from_cluster(
    row_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ImportService(db)
    try:
        return service.detach_row_from_cluster(user_id=current_user.id, row_id=row_id)
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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


@router.get("/{session_id}/clusters", response_model=BulkClustersResponse)
def get_bulk_clusters(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return bulk-eligible clusters (И-08 Этап 2).

    Fingerprint clusters of size ≥5, plus brand-level groups that aggregate
    ≥2 fingerprints into a single row-count ≥5 block. Transfer-secondary
    rows are pre-filtered so they never appear in the bulk UI — they're
    auto-created via their transfer pair on commit.
    """
    service = ImportService(db)
    try:
        return service.get_bulk_clusters(user_id=current_user.id, session_id=session_id)
    except ImportNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{session_id}/rows/{row_id}/attach-to-cluster",
    response_model=AttachRowToClusterResponse,
)
def attach_row_to_cluster(
    session_id: int,
    row_id: int,
    payload: AttachRowToClusterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move a "needs attention" row into an existing cluster.

    Creates a user-scoped FingerprintAlias so future imports with the same
    source pattern land in the target cluster automatically (Level 3). The
    row is committed atomically using the target cluster's suggested category.
    """
    service = ImportService(db)
    try:
        return service.attach_row_to_cluster(
            user_id=current_user.id,
            session_id=session_id,
            row_id=row_id,
            target_fingerprint=payload.target_fingerprint,
            counterparty_id=payload.counterparty_id,
        )
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{session_id}/clusters/bulk-apply", response_model=BulkApplyResponse)
def bulk_apply_cluster(
    session_id: int,
    payload: BulkApplyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a moderator action to all included rows of a cluster.

    One click, N confirmations (see project_bulk_clusters.md). Each row is
    confirmed via the same path as a manual single-row update. Rules are
    upserted per unique (fingerprint, category) combination with
    `confirms_delta = N` — a single bulk action activates AND generalizes
    the rule in one transition.
    """
    service = ImportService(db)
    try:
        return service.bulk_apply_cluster(
            user_id=current_user.id, session_id=session_id, payload=payload,
        )
    except ImportNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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


@router.patch("/{session_id}/account")
def assign_session_account(
    session_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Assign (or re-assign) an account to an import session and re-run transfer matching."""
    service = ImportService(db)
    session = service.import_repo.get_session(session_id=session_id, user_id=current_user.id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена.")
    account_id = payload.get("account_id")
    if not account_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="account_id обязателен.")
    service.import_repo.update_session(session, account_id=int(account_id))
    db.commit()
    db.refresh(session)

    # If the session was uploaded without a detected account (very common when
    # the user had no existing statements for this bank yet), auto-preview was
    # skipped on upload. Now that we have an account, fire it — so the bulk
    # flow "upload N statements → assign each to an account" matches the
    # queue-era UX where rows get extracted and matched without manual clicks.
    if session.status == "analyzed":
        mapping = session.mapping_json or {}
        field_mapping = mapping.get("field_mapping") or {}
        if field_mapping.get("date") and field_mapping.get("amount"):
            try:
                from app.jobs.auto_preview_import_session import auto_preview_import_session
                auto_preview_import_session.delay(session.id)
            except Exception:
                pass

    # Trigger the debounced global transfer matcher so existing previewed
    # sessions can now match against this one.
    try:
        from app.jobs.transfer_matcher_debounced import schedule_transfer_match
        schedule_transfer_match(current_user.id)
    except Exception:
        pass
    return {
        "id": session.id,
        "filename": session.filename,
        "source_type": session.source_type,
        "status": session.status,
        "account_id": session.account_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


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
