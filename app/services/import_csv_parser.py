from __future__ import annotations

import csv
import io


def parse_csv_content(*, content: str, delimiter: str = ",", has_header: bool = True) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return [], []

    if has_header:
        headers = [normalize_header_name(value, idx) for idx, value in enumerate(rows[0])]
        data_rows = rows[1:]
    else:
        max_columns = max(len(row) for row in rows)
        headers = [f"column_{idx + 1}" for idx in range(max_columns)]
        data_rows = rows

    normalized_rows: list[dict[str, str]] = []
    for raw_row in data_rows:
        item: dict[str, str] = {}
        for idx, header in enumerate(headers):
            item[header] = (raw_row[idx].strip() if idx < len(raw_row) else "")
        if any(value.strip() for value in item.values()):
            normalized_rows.append(item)
    return headers, normalized_rows


def normalize_header_name(value: str, fallback_idx: int) -> str:
    normalized = value.strip()
    if normalized:
        return normalized
    return f"column_{fallback_idx + 1}"
