from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.import_validator import ImportRowValidationError, parse_date, parse_decimal


class ImportNormalizer:
    def normalize_row(
        self,
        *,
        raw_row: dict[str, str],
        field_mapping: dict[str, str | None],
        date_format: str,
        default_currency: str,
    ) -> dict[str, Any]:
        date_key = field_mapping.get("date")
        description_key = field_mapping.get("description")
        amount_key = field_mapping.get("amount")
        income_key = field_mapping.get("income")
        expense_key = field_mapping.get("expense")
        direction_key = field_mapping.get("direction")
        currency_key = field_mapping.get("currency")
        balance_key = field_mapping.get("balance_after")
        counterparty_key = field_mapping.get("counterparty")
        raw_type_key = field_mapping.get("raw_type")
        account_hint_key = field_mapping.get("account_hint")
        reference_key = field_mapping.get("source_reference")

        if not date_key or not description_key:
            raise ImportRowValidationError("Не удалось определить обязательные поля даты и описания.")

        date_raw = (raw_row.get(date_key) or "").strip()
        description = (raw_row.get(description_key) or "").strip()
        if not date_raw:
            raise ImportRowValidationError("Пустая дата операции.")
        if not description:
            raise ImportRowValidationError("Пустое описание операции.")

        transaction_date = parse_date(date_raw, date_format)
        if transaction_date.tzinfo is None:
            transaction_date = transaction_date.replace(tzinfo=timezone.utc)

        amount: Decimal
        direction: str
        if amount_key:
            amount_raw = (raw_row.get(amount_key) or "").strip()
            if not amount_raw:
                raise ImportRowValidationError("Пустая сумма операции.")
            amount_value = parse_decimal(amount_raw)
            if amount_value == 0:
                raise ImportRowValidationError("Сумма операции равна нулю.")
            direction = self._resolve_direction(direction_raw=(raw_row.get(direction_key) or "") if direction_key else "", amount_value=amount_value)
            amount = abs(amount_value)
        else:
            income_raw = (raw_row.get(income_key or "") or "").strip() if income_key else ""
            expense_raw = (raw_row.get(expense_key or "") or "").strip() if expense_key else ""
            if income_raw:
                amount = parse_decimal(income_raw)
                direction = "income"
            elif expense_raw:
                amount = parse_decimal(expense_raw)
                direction = "expense"
            else:
                raise ImportRowValidationError("Не удалось определить сумму операции.")
            amount = abs(amount)

        currency = ((raw_row.get(currency_key) or "").strip().upper() if currency_key else "") or default_currency.upper()
        balance_after = self._safe_decimal(raw_row.get(balance_key)) if balance_key else None

        return {
            "date": transaction_date.isoformat(),
            "description": description,
            "amount": str(amount),
            "currency": currency,
            "direction": direction,
            "account_hint": (raw_row.get(account_hint_key) or "").strip() if account_hint_key else None,
            "counterparty": (raw_row.get(counterparty_key) or "").strip() if counterparty_key else None,
            "raw_type": (raw_row.get(raw_type_key) or "").strip() if raw_type_key else None,
            "balance_after": str(balance_after) if balance_after is not None else None,
            "source_reference": (raw_row.get(reference_key) or "").strip() if reference_key else None,
        }

    @staticmethod
    def _resolve_direction(*, direction_raw: str, amount_value: Decimal) -> str:
        token = direction_raw.strip().lower()
        if token:
            if any(word in token for word in ["income", "credit", "приход", "зачис", "пополн"]):
                return "income"
            if any(word in token for word in ["expense", "debit", "расход", "спис", "оплата"]):
                return "expense"
        return "expense" if amount_value < 0 else "income"

    @staticmethod
    def _safe_decimal(value: str | None) -> Decimal | None:
        text = (value or "").strip()
        if not text:
            return None
        return parse_decimal(text)
