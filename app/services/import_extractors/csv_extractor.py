from __future__ import annotations

import csv
import io
from typing import Any

from app.services.import_extractors.base import BaseExtractor, ExtractedTable, ExtractionResult


class CsvExtractor(BaseExtractor):
    source_type = "csv"

    def extract(self, *, filename: str, raw_bytes: bytes, options: dict[str, Any] | None = None) -> ExtractionResult:
        opts = options or {}
        delimiter = opts.get("delimiter", ",") or ","
        has_header = bool(opts.get("has_header", True))

        try:
            content = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw_bytes.decode("cp1251")

        stream = io.StringIO(content)
        reader = csv.reader(stream, delimiter=delimiter)
        rows = [list(row) for row in reader if any(str(cell).strip() for cell in row)]
        if not rows:
            return ExtractionResult(source_type=self.source_type, tables=[], meta={"row_count": 0})

        if has_header:
            raw_header = rows[0]
            data_rows = rows[1:]
            columns = [self._normalize_header(name, idx) for idx, name in enumerate(raw_header)]
        else:
            width = max(len(row) for row in rows)
            columns = [f"column_{index + 1}" for index in range(width)]
            data_rows = rows

        normalized_rows = [
            {columns[idx]: (row[idx].strip() if idx < len(row) and row[idx] is not None else "") for idx in range(len(columns))}
            for row in data_rows
        ]

        return ExtractionResult(
            source_type=self.source_type,
            tables=[ExtractedTable(name="csv", columns=columns, rows=normalized_rows, confidence=0.98)],
            meta={"row_count": len(normalized_rows), "delimiter": delimiter, "has_header": has_header, "text_content": content},
        )

    @staticmethod
    def _normalize_header(value: str | None, idx: int) -> str:
        text = (value or "").strip()
        return text or f"column_{idx + 1}"
