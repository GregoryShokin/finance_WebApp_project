from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


class ImportRowValidationError(Exception):
    pass


CURRENCY_MARKERS_RX = re.compile(r"(?:₽|RUB|РУБ|USD|EUR)$", re.I)


def parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    normalized = value.strip()
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = CURRENCY_MARKERS_RX.sub("", normalized).strip()
    normalized = normalized.replace(" ", "")
    if not normalized:
        return None
    normalized = normalized.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ImportRowValidationError(f"Не удалось распознать сумму: {value}") from exc


def parse_date(value: str, date_format: str) -> datetime:
    try:
        return datetime.strptime(value.strip(), date_format)
    except ValueError as exc:
        raise ImportRowValidationError(f"Не удалось распознать дату: {value}") from exc
