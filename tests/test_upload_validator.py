"""Tests for the upload validator (Этап 0.2).

Covers the three classes of attack the validator exists to block:
  - oversized uploads exhausting RAM,
  - mislabelled files smuggling the wrong magic past extension checks,
  - zip-bomb XLSX payloads.

Plus boundary cases — `>` vs `>=` is the most common fence-post bug in
size-check code, so exact-at-limit and one-over-limit are explicit tests.

The streaming guarantee (we DO NOT keep reading past the cap) is validated
by counting `read()` invocations against a synthetic stream rather than by
behavior under concurrency — that's the only way to prove "we stopped early"
without spinning up real workers.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from app.core.config import settings
from app.services.upload_validator import (
    UnsupportedUploadTypeError,
    UploadTooLargeError,
    detect_magic_kind,
    is_plausibly_csv,
    read_upload_with_limits,
    validate_xlsx_zip_metadata,
)


PDF_HEAD = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
ZIP_HEAD = b"PK\x03\x04"


def _mb(n: float) -> int:
    return int(n * 1024 * 1024)


def _make_xlsx_zip(*, decompressed_size: int = 0, include_workbook: bool = True) -> bytes:
    """Build a minimal valid .xlsx archive (or a deliberately malformed one).

    `decompressed_size` is the uncompressed length of the workbook payload —
    pass a huge value to simulate a zip-bomb in conjunction with `ZIP_DEFLATED`,
    which compresses long runs of identical bytes very tightly.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if include_workbook:
            payload = b"x" * decompressed_size if decompressed_size else b"<workbook/>"
            archive.writestr("xl/workbook.xml", payload)
        else:
            archive.writestr("not-a-workbook.txt", b"hello")
    return buffer.getvalue()


class CountingStream:
    """In-memory async file mock that tracks how many times `read` was called."""

    def __init__(self, data: bytes, filename: str = "file.bin", chunk_size: int = 64 * 1024):
        self.data = data
        self.pos = 0
        self.read_count = 0
        self.filename = filename
        self._chunk_size = chunk_size

    async def read(self, n: int = -1) -> bytes:
        self.read_count += 1
        if n < 0:
            chunk = self.data[self.pos:]
            self.pos = len(self.data)
        else:
            chunk = self.data[self.pos:self.pos + n]
            self.pos += len(chunk)
        return chunk


# ─── magic detection ─────────────────────────────────────────────────────────


def test_detect_pdf_by_magic():
    assert detect_magic_kind(PDF_HEAD) == "pdf"


def test_detect_xlsx_only_when_extension_hints_xlsx():
    # Bare ZIP header with no .xlsx hint — could be docx/jar/zip → unknown.
    assert detect_magic_kind(ZIP_HEAD) == "unknown"
    assert detect_magic_kind(ZIP_HEAD, declared_extension="xlsx") == "xlsx"
    assert detect_magic_kind(ZIP_HEAD, declared_extension="docx") == "unknown"


def test_detect_csv_passes_negative_check():
    assert detect_magic_kind(b"date,amount,description\n2026-01-01,100.00,Coffee\n") == "csv"


def test_detect_unknown_returns_unknown():
    # Random binary garbage that isn't PDF/ZIP/text.
    assert detect_magic_kind(b"\x89\x00\x01\x02\x03binary\x00") == "unknown"


# ─── CSV negative-check ──────────────────────────────────────────────────────


def test_csv_negative_check_rejects_null_bytes():
    assert is_plausibly_csv(b"date,amount\x00\n2026-01-01,100\n") is False


def test_csv_negative_check_rejects_pdf_magic():
    # PDF header isn't csv-shaped — `%`, `P`, `D`, `F` are printable, but
    # the body has binary. We test on a representative slice.
    assert is_plausibly_csv(PDF_HEAD + b"\x00binary\x01stuff") is False


def test_csv_negative_check_accepts_cp1251_russian_bank_statement():
    # Real-world: a Russian bank exports headers and counterparty names in
    # cp1251 (high-bit bytes, no nulls). Must pass.
    cp1251 = "Дата,Сумма,Описание\n2026-01-01,100.00,Кофе\n".encode("cp1251")
    assert b"\x00" not in cp1251  # sanity
    assert is_plausibly_csv(cp1251) is True


def test_csv_negative_check_rejects_empty_input():
    assert is_plausibly_csv(b"") is False


def test_csv_short_one_line_passes():
    """Regression guard: a tiny one-row statement (~30 bytes) must not be
    rejected by the 95% printable threshold just because the sample is small."""
    assert is_plausibly_csv(b"date,amount\n2026-01-01,100") is True


# ─── XLSX zip metadata ──────────────────────────────────────────────────────


def test_xlsx_valid_archive_passes():
    valid = _make_xlsx_zip(include_workbook=True)
    validate_xlsx_zip_metadata(valid)  # no raise


def test_xlsx_zip_without_workbook_xml_rejected():
    bogus = _make_xlsx_zip(include_workbook=False)
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        validate_xlsx_zip_metadata(bogus)
    assert exc.value.code == "xlsx_missing_manifest"


def test_xlsx_decompression_bomb_rejected():
    # 1 GB of identical bytes deflates to a few KB. cap is MAX_XLSX_DECOMPRESSED_MB.
    bomb_size = (settings.MAX_XLSX_DECOMPRESSED_MB + 50) * 1024 * 1024
    bomb = _make_xlsx_zip(decompressed_size=bomb_size)
    # On-disk size of `bomb` is small (zip-bomb compresses well); test sanity:
    assert len(bomb) < 5 * 1024 * 1024
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        validate_xlsx_zip_metadata(bomb)
    assert exc.value.code == "xlsx_decompression_too_large"


def test_xlsx_invalid_archive_bytes_rejected():
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        validate_xlsx_zip_metadata(b"PK\x03\x04not really a zip")
    assert exc.value.code == "xlsx_invalid_archive"


# ─── streaming + size limits (read_upload_with_limits) ──────────────────────


@pytest.mark.asyncio
async def test_pdf_within_limit_passes():
    body = PDF_HEAD + b"\n" + b"a" * (_mb(1) - len(PDF_HEAD) - 1)
    stream = CountingStream(body, filename="statement.pdf")
    raw, kind = await read_upload_with_limits(stream, declared_extension="pdf")
    assert kind == "pdf"
    assert len(raw) == len(body)


@pytest.mark.asyncio
async def test_pdf_exactly_at_limit_passes():
    cap = _mb(settings.MAX_UPLOAD_SIZE_PDF_MB)
    body = PDF_HEAD + b"a" * (cap - len(PDF_HEAD))
    assert len(body) == cap
    stream = CountingStream(body, filename="statement.pdf")
    raw, kind = await read_upload_with_limits(stream, declared_extension="pdf")
    assert kind == "pdf"
    assert len(raw) == cap


@pytest.mark.asyncio
async def test_pdf_one_byte_over_limit_fails():
    cap = _mb(settings.MAX_UPLOAD_SIZE_PDF_MB)
    body = PDF_HEAD + b"a" * (cap - len(PDF_HEAD) + 1)
    assert len(body) == cap + 1
    stream = CountingStream(body, filename="statement.pdf")
    with pytest.raises(UploadTooLargeError) as exc:
        await read_upload_with_limits(stream, declared_extension="pdf")
    assert exc.value.kind == "pdf"
    assert exc.value.max_size_mb == settings.MAX_UPLOAD_SIZE_PDF_MB


@pytest.mark.asyncio
async def test_csv_above_limit_raises_too_large():
    cap = _mb(settings.MAX_UPLOAD_SIZE_CSV_MB)
    body = b"date,amount\n" + b"a" * cap
    stream = CountingStream(body, filename="statement.csv")
    with pytest.raises(UploadTooLargeError) as exc:
        await read_upload_with_limits(stream, declared_extension="csv")
    assert exc.value.kind == "csv"


@pytest.mark.asyncio
async def test_xlsx_within_limit_passes():
    body = _make_xlsx_zip()
    stream = CountingStream(body, filename="statement.xlsx")
    raw, kind = await read_upload_with_limits(stream, declared_extension="xlsx")
    assert kind == "xlsx"
    assert raw == body


@pytest.mark.asyncio
async def test_pdf_extension_with_xlsx_magic_bytes_raises_unsupported():
    body = _make_xlsx_zip()  # ZIP magic, declared as PDF
    stream = CountingStream(body, filename="statement.pdf")
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        await read_upload_with_limits(stream, declared_extension="pdf")
    # ZIP without xlsx hint → unknown → unsupported_upload_type, before mismatch check.
    assert exc.value.code in {"unsupported_upload_type", "extension_content_mismatch"}


@pytest.mark.asyncio
async def test_csv_extension_with_pdf_magic_bytes_raises_unsupported():
    body = PDF_HEAD + b"more pdf body"
    stream = CountingStream(body, filename="statement.csv")
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        await read_upload_with_limits(stream, declared_extension="csv")
    assert exc.value.code == "extension_content_mismatch"


@pytest.mark.asyncio
async def test_unknown_extension_with_garbage_bytes_raises_unsupported():
    body = b"\x89\x00binary\x00garbage" * 10
    stream = CountingStream(body, filename="weird.bin")
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        await read_upload_with_limits(stream, declared_extension="bin")
    assert exc.value.code == "unsupported_upload_type"


@pytest.mark.asyncio
async def test_empty_file_raises_unsupported():
    stream = CountingStream(b"", filename="statement.csv")
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        await read_upload_with_limits(stream, declared_extension="csv")
    assert exc.value.code == "empty_file"


@pytest.mark.asyncio
async def test_streaming_does_not_buffer_above_limit():
    """Hostile stream: 100 MB PDF. We must stop early — read_count should be
    bounded by ~max(per-type cap)/64KB, not by the total stream size."""
    body = PDF_HEAD + b"x" * _mb(100)  # 100 MB stream, 25 MB pdf cap
    stream = CountingStream(body, filename="statement.pdf")
    with pytest.raises(UploadTooLargeError):
        await read_upload_with_limits(stream, declared_extension="pdf")
    # 25 MB cap / 64 KB chunks = 400 chunks. Allow 50% slack for detection
    # phase, but the bound MUST be far below 100 MB / 64 KB = 1600.
    assert stream.read_count < 600, (
        f"streaming kept reading past the cap: {stream.read_count} chunks consumed"
    )


@pytest.mark.asyncio
async def test_xlsx_zip_bomb_through_full_pipeline():
    bomb_size = (settings.MAX_XLSX_DECOMPRESSED_MB + 50) * 1024 * 1024
    bomb = _make_xlsx_zip(decompressed_size=bomb_size)
    # On-disk size is small (deflated), so the per-type 10 MB cap should NOT trip.
    assert len(bomb) < settings.MAX_UPLOAD_SIZE_XLSX_MB * 1024 * 1024
    stream = CountingStream(bomb, filename="bomb.xlsx")
    with pytest.raises(UnsupportedUploadTypeError) as exc:
        await read_upload_with_limits(stream, declared_extension="xlsx")
    assert exc.value.code == "xlsx_decompression_too_large"


@pytest.mark.asyncio
async def test_csv_with_cp1251_russian_text_passes():
    body = "Дата,Сумма,Описание\n2026-01-01,100.00,Кофе\n".encode("cp1251") * 200
    stream = CountingStream(body, filename="statement.csv")
    raw, kind = await read_upload_with_limits(stream, declared_extension="csv")
    assert kind == "csv"
    assert raw == body
