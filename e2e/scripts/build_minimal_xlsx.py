"""Build a minimal valid XLSX with a tiny dataset for the upload happy-path test.

Output: `e2e/fixtures/statements-synthetic/tiny-valid.xlsx`. Contains 3 rows
(date, description, amount) — enough for `validate_xlsx_zip_metadata` to pass,
and for the import service to attempt extraction.

We don't depend on openpyxl / pandas to keep e2e Node-only; the zipfile +
hand-rolled XML approach mirrors `build_zip_bomb.py`.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "fixtures" / "statements-synthetic" / "tiny-valid.xlsx"

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
    '</Types>'
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)
WORKBOOK_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets>'
    '</workbook>'
)
WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
    '</Relationships>'
)
SHARED_STRINGS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="6" uniqueCount="6">'
    '<si><t>Дата</t></si>'
    '<si><t>Описание</t></si>'
    '<si><t>Сумма</t></si>'
    '<si><t>Покупка в магазине</t></si>'
    '<si><t>Зарплата</t></si>'
    '<si><t>Аренда</t></si>'
    '</sst>'
)
SHEET = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheetData>'
    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>'
    '<row r="2"><c r="A2"><v>2026-01-01</v></c><c r="B2" t="s"><v>3</v></c><c r="C2"><v>-100.50</v></c></row>'
    '<row r="3"><c r="A3"><v>2026-01-02</v></c><c r="B3" t="s"><v>4</v></c><c r="C3"><v>50000</v></c></row>'
    '<row r="4"><c r="A4"><v>2026-01-03</v></c><c r="B4" t="s"><v>5</v></c><c r="C4"><v>-25000</v></c></row>'
    '</sheetData>'
    '</worksheet>'
)


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("xl/workbook.xml", WORKBOOK_XML)
        zf.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        zf.writestr("xl/sharedStrings.xml", SHARED_STRINGS)
        zf.writestr("xl/worksheets/sheet1.xml", SHEET)
    OUTPUT.write_bytes(buffer.getvalue())
    print(f"wrote {OUTPUT} — {OUTPUT.stat().st_size:,} bytes")


if __name__ == "__main__":
    build()
