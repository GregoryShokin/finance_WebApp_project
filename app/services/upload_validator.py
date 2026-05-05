"""Upload-time validation: size limit + magic-byte content-type whitelist.

This module is the single point of truth for what kinds of files we accept
on `/imports/upload` and `/telegram/bot/upload`. Three checks, in order:

1. **Size**, streamed in 64 KB chunks — we never let `await file.read()` pull
   a 500 MB blob into RAM unconditionally. The chunk after the limit is
   thrown away with a 413, not buffered.
2. **Magic bytes**, not the `Content-Type` header (which the client controls
   and the user could spoof) and not the filename extension alone (a `.csv`
   could really be a PDF).
3. **Format-specific deep checks**: for XLSX (which is a ZIP) we walk the
   archive metadata to reject zip-bomb uploads — a 10 KB XLSX that
   decompresses to 4 GB and OOMs the worker is a known attack class.

The validator returns the raw bytes — extractors downstream still expect
`bytes`/`BytesIO`, and a tempfile-based pipeline is a deliberate post-MVP
trade-off (see `architecture_decisions.md`).
"""
from __future__ import annotations

import io
import zipfile
from typing import Literal

from fastapi import UploadFile

from app.core.config import settings


READ_CHUNK_SIZE = 64 * 1024  # 64 KB

# Bytes inspected for magic-type detection. PDF/XLSX signatures live in the
# first 8 bytes; CSV plausibility uses 4 KB as a representative window.
MAGIC_BYTES_PROBE = 8
CSV_PROBE_BYTES = 4 * 1024

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"

# CSV negative-check: reject control characters except whitespace.
_CSV_ALLOWED_CONTROL = {0x09, 0x0A, 0x0D}  # \t \n \r
_CSV_PRINTABLE_RATIO_MIN = 0.95

DetectedKind = Literal["pdf", "xlsx", "csv", "unknown"]


class UploadValidationError(Exception):
    """Base class — every error below maps to either 413 or 415 in the route.

    `to_payload()` returns the JSON body the route renders directly via
    `JSONResponse`. The shape is flat (no nested `detail` wrapper) so the
    frontend reads `payload.code` instead of `payload.detail.code`.
    """

    code: str = "upload_invalid"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_payload(self) -> dict:
        return {"detail": str(self), "code": self.code}


class UploadTooLargeError(UploadValidationError):
    """Maps to HTTP 413."""

    code = "upload_too_large"

    def __init__(self, *, max_size_mb: int, actual_size_mb: float, kind: str):
        super().__init__(
            f"Файл слишком большой: {actual_size_mb:.1f} MB при лимите {max_size_mb} MB для {kind}.",
        )
        self.max_size_mb = max_size_mb
        self.actual_size_mb = actual_size_mb
        self.kind = kind

    def to_payload(self) -> dict:
        return {
            **super().to_payload(),
            "max_size_mb": self.max_size_mb,
            "actual_size_mb": round(self.actual_size_mb, 2),
            "kind": self.kind,
        }


class UnsupportedUploadTypeError(UploadValidationError):
    """Maps to HTTP 415."""

    code = "unsupported_upload_type"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        actual_decompressed_mb: float | None = None,
        max_decompressed_mb: int | None = None,
    ):
        super().__init__(message, code=code)
        self.actual_decompressed_mb = actual_decompressed_mb
        self.max_decompressed_mb = max_decompressed_mb

    def to_payload(self) -> dict:
        payload = super().to_payload()
        if self.actual_decompressed_mb is not None:
            payload["actual_decompressed_mb"] = round(self.actual_decompressed_mb, 2)
        if self.max_decompressed_mb is not None:
            payload["max_decompressed_mb"] = self.max_decompressed_mb
        return payload


# ─── helpers ──────────────────────────────────────────────────────────────────


def _max_size_bytes(kind: DetectedKind) -> int:
    if kind == "pdf":
        return settings.MAX_UPLOAD_SIZE_PDF_MB * 1024 * 1024
    if kind == "xlsx":
        return settings.MAX_UPLOAD_SIZE_XLSX_MB * 1024 * 1024
    if kind == "csv":
        return settings.MAX_UPLOAD_SIZE_CSV_MB * 1024 * 1024
    # Unknown types are rejected on type, but pick the smallest cap defensively
    # to keep the streaming reader from running away if the type-check is bypassed.
    return min(
        settings.MAX_UPLOAD_SIZE_CSV_MB,
        settings.MAX_UPLOAD_SIZE_XLSX_MB,
        settings.MAX_UPLOAD_SIZE_PDF_MB,
    ) * 1024 * 1024


def _normalize_extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].strip().lower()


def detect_magic_kind(head: bytes, *, declared_extension: str = "") -> DetectedKind:
    """Map probe bytes to a content kind. Filename extension is only used to
    distinguish XLSX (ZIP signature) from a generic ZIP — XLSX *is* a ZIP, so
    the magic alone can't tell them apart."""
    if head.startswith(PDF_MAGIC):
        return "pdf"
    if head.startswith(ZIP_MAGIC):
        # Without an .xlsx hint we can't tell xlsx from .zip/.docx/.jar — defer
        # to declared extension, then deep-check in `validate_xlsx_zip_metadata`.
        if declared_extension == "xlsx":
            return "xlsx"
        return "unknown"
    if is_plausibly_csv(head):
        return "csv"
    return "unknown"


def is_plausibly_csv(head: bytes) -> bool:
    """Negative-check that a byte window could be CSV.

    Rejects null-bytes (strong binary signal) and runs-of-control-characters.
    Tolerates high-bit bytes (>=0x80) so cp1251 / latin-1 / multi-byte UTF-8
    statements from Russian banks pass.
    """
    if not head:
        return False
    if b"\x00" in head:
        return False
    printable = 0
    for b in head:
        if b in _CSV_ALLOWED_CONTROL:
            printable += 1
        elif 0x20 <= b <= 0x7E:
            printable += 1
        elif b >= 0x80:
            printable += 1
    return printable / len(head) > _CSV_PRINTABLE_RATIO_MIN


def validate_xlsx_zip_metadata(content: bytes) -> None:
    """Reject zip-bomb XLSX and ZIPs that aren't really XLSX.

    Reads ONLY the central directory (zipfile lazy-parses), so memory cost
    stays close to the upload size — we don't decompress anything here.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise UnsupportedUploadTypeError(
            "Файл с расширением .xlsx не похож на корректный XLSX-архив.",
            code="xlsx_invalid_archive",
        ) from exc

    if not any(info.filename == "xl/workbook.xml" for info in infos):
        # Generic ZIP / DOCX / JAR — not an XLSX.
        raise UnsupportedUploadTypeError(
            "Файл с расширением .xlsx не похож на корректный XLSX-архив.",
            code="xlsx_missing_manifest",
        )

    total_uncompressed = sum(info.file_size for info in infos)
    cap = settings.MAX_XLSX_DECOMPRESSED_MB * 1024 * 1024
    if total_uncompressed > cap:
        raise UnsupportedUploadTypeError(
            f"XLSX распаковывается в {total_uncompressed / 1024 / 1024:.1f} MB при лимите "
            f"{settings.MAX_XLSX_DECOMPRESSED_MB} MB. Возможный zip-bomb.",
            code="xlsx_decompression_too_large",
            actual_decompressed_mb=total_uncompressed / 1024 / 1024,
            max_decompressed_mb=settings.MAX_XLSX_DECOMPRESSED_MB,
        )


# ─── public entry point ───────────────────────────────────────────────────────


async def read_upload_with_limits(
    upload_file: UploadFile,
    *,
    declared_extension: str | None = None,
) -> tuple[bytes, DetectedKind]:
    """Stream the upload into memory, enforcing size + content-type checks.

    Returns `(raw_bytes, detected_kind)`. The detected kind is what we trust
    for routing into extractors — never the filename extension, which the
    client can spoof. Raises `UploadTooLargeError` (→ 413) or
    `UnsupportedUploadTypeError` (→ 415).

    NOTE: Files are accumulated in BytesIO (RAM). For 100 concurrent uploads
    of 25 MB PDFs that's ~2.5 GB peak — acceptable for the current single-box
    deployment. A tempfile-backed pipeline would lower this to ~2 MB/upload
    in RAM but requires reworking ImportExtractorRegistry to take a path
    instead of bytes. Tracked as a post-MVP backlog item.
    """
    extension = (declared_extension or _normalize_extension(upload_file.filename)).lower()

    # Phase 1: read enough to detect type. We bound this by max(per-type cap)
    # so a hostile client streaming an endless PDF doesn't keep us reading
    # past 25 MB.
    hard_cap = max(
        settings.MAX_UPLOAD_SIZE_CSV_MB,
        settings.MAX_UPLOAD_SIZE_XLSX_MB,
        settings.MAX_UPLOAD_SIZE_PDF_MB,
    ) * 1024 * 1024

    buffer = bytearray()
    detected: DetectedKind | None = None
    type_cap_bytes = hard_cap  # tightened once we know the kind

    while True:
        chunk = await upload_file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)

        if detected is None and len(buffer) >= MAGIC_BYTES_PROBE:
            head = bytes(buffer[:max(MAGIC_BYTES_PROBE, CSV_PROBE_BYTES)])
            detected = detect_magic_kind(head, declared_extension=extension)
            if detected == "unknown":
                raise UnsupportedUploadTypeError(
                    "Тип файла не распознан. Поддерживаются CSV, XLSX и PDF.",
                    code="unsupported_upload_type",
                )
            type_cap_bytes = _max_size_bytes(detected)

            # Cross-check declared extension vs detected magic. A `.csv` that
            # is really a PDF is rejected here — extension is not authoritative,
            # but a mismatch is a strong sign the file was misnamed or hostile.
            if extension and extension != detected:
                raise UnsupportedUploadTypeError(
                    f"Файл с расширением .{extension} не соответствует реальному содержимому ({detected}).",
                    code="extension_content_mismatch",
                )

        if len(buffer) > type_cap_bytes:
            kind_for_error = detected or "файла"
            cap_mb = type_cap_bytes // (1024 * 1024)
            raise UploadTooLargeError(
                max_size_mb=cap_mb,
                actual_size_mb=len(buffer) / 1024 / 1024,
                kind=str(kind_for_error),
            )

    # File ended before we collected enough bytes to detect — empty or near-empty.
    if detected is None:
        if not buffer:
            raise UnsupportedUploadTypeError(
                "Файл пустой.",
                code="empty_file",
            )
        # Try one last detection on whatever we have.
        head = bytes(buffer[:max(MAGIC_BYTES_PROBE, CSV_PROBE_BYTES)])
        detected = detect_magic_kind(head, declared_extension=extension)
        if detected == "unknown":
            raise UnsupportedUploadTypeError(
                "Тип файла не распознан. Поддерживаются CSV, XLSX и PDF.",
                code="unsupported_upload_type",
            )
        if extension and extension != detected:
            raise UnsupportedUploadTypeError(
                f"Файл с расширением .{extension} не соответствует реальному содержимому ({detected}).",
                code="extension_content_mismatch",
            )
        if len(buffer) > _max_size_bytes(detected):
            raise UploadTooLargeError(
                max_size_mb=_max_size_bytes(detected) // (1024 * 1024),
                actual_size_mb=len(buffer) / 1024 / 1024,
                kind=detected,
            )

    raw = bytes(buffer)

    if detected == "xlsx":
        validate_xlsx_zip_metadata(raw)

    return raw, detected
