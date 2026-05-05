"""Build a tiny-on-disk, large-decompressed XLSX for upload-validator tests.

The output file is committed to `e2e/fixtures/adversarial/zip-bomb.xlsx`.
Re-run this script if the validator changes its zip-bomb cap or the manifest
requirements (currently: must contain `xl/workbook.xml` per
`app/services/upload_validator.py`).

Mechanism: a valid minimal XLSX structure (so `xlsx_missing_manifest` doesn't
fire) plus one extra entry whose uncompressed size is ~200 MB but compresses
to <100 KB because it's a stream of identical bytes. Total file on disk
~250 KB.

This is NOT a real exploit — `validate_xlsx_zip_metadata` rejects it on
`xlsx_decompression_too_large` (cap 100 MB). The fixture exists to verify
that rejection.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "fixtures" / "adversarial" / "zip-bomb.xlsx"

# 200 MB of identical zero bytes — compresses extremely well.
BOMB_SIZE_MB = 200
BOMB_BYTES = b"\x00" * (BOMB_SIZE_MB * 1024 * 1024)

# Minimal valid XLSX skeleton — enough for `validate_xlsx_zip_metadata` to
# pass the manifest check and reach the decompression-size check.
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '</Types>'
)
RELS_DOTRELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)
WORKBOOK_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>'
)


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", RELS_DOTRELS)
        zf.writestr("xl/workbook.xml", WORKBOOK_XML)
        # The bomb payload — must NOT be xl/workbook.xml itself; we keep it as
        # a benign-looking sheet entry. file_size on the ZipInfo reflects the
        # original 200 MB, which is what validate_xlsx_zip_metadata sums.
        zf.writestr("xl/worksheets/sheet1.xml", BOMB_BYTES)
    raw = buffer.getvalue()
    OUTPUT.write_bytes(raw)
    print(f"wrote {OUTPUT} — {len(raw):,} bytes on disk, {BOMB_SIZE_MB} MB decompressed")


if __name__ == "__main__":
    build()
