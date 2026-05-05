"""Shared upload-validation flow for /imports/upload and /telegram/bot/upload.

Owns two responsibilities the route shouldn't duplicate:
  - calling `read_upload_with_limits` with the right declared extension,
  - guaranteeing `await file.close()` even on validation failure.

Doesn't know about HTTP status codes or response bodies — the route catches
`UploadValidationError` subclasses and renders them via `JSONResponse(...,
e.to_payload())`. Keeping this layer transport-agnostic means a future
non-FastAPI caller (Celery task, CLI ingest) can reuse the helper as-is.
"""
from __future__ import annotations

from fastapi import UploadFile

from app.services.upload_validator import (
    DetectedKind,
    read_upload_with_limits,
)


def extract_extension(filename: str | None) -> str:
    """Returns the lowercased extension without the dot, or `""` if absent.
    Mirrors `_normalize_extension` in the validator — duplicated here so the
    route can pre-compute the hint before invoking the helper."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].strip().lower()


async def validate_and_read_upload(
    file: UploadFile,
    *,
    declared_extension: str | None = None,
) -> tuple[bytes, DetectedKind]:
    """Stream-read the upload with all validator checks, always closing `file`.

    Returns `(content_bytes, detected_kind)` on success. Re-raises
    `UploadTooLargeError` / `UnsupportedUploadTypeError` from the validator
    unchanged so the caller can map them to 413 / 415.

    The `await file.close()` runs in `finally` so a partially consumed
    upload doesn't leak the underlying spooled tempfile / socket buffer.
    `bytes` already in memory survive close — the validator returns its
    own `bytes` accumulated in BytesIO, not a view over the file handle.
    """
    extension = (
        declared_extension
        if declared_extension is not None
        else extract_extension(file.filename)
    )
    try:
        return await read_upload_with_limits(file, declared_extension=extension)
    finally:
        try:
            await file.close()
        except Exception:
            # Idempotent close — already-closed handles must not break the
            # validation flow's exception propagation.
            pass
