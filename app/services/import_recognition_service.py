from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services.import_confidence import ImportConfidenceService
from app.services.import_extractors.base import ExtractedTable

HEADER_SYNONYMS: dict[str, list[str]] = {
    "date": ["date", "дата", "operation date", "posted"],
    "description": ["description", "details", "назнач", "опис", "merchant", "comment", "контрагент", "операция"],
    "amount": ["amount", "sum", "сумма", "итог", "total"],
    "income": ["income", "credit", "приход", "зачис", "пополн"],
    "expense": ["expense", "debit", "расход", "спис", "withdraw"],
    "currency": ["currency", "валюта"],
    "direction": ["direction", "type", "вид", "направление", "debit/credit", "дебет", "кредит"],
    "balance_after": ["balance", "остаток", "баланс"],
    "counterparty": ["counterparty", "recipient", "sender", "получатель", "отправитель", "контрагент"],
    "raw_type": ["operation type", "тип операции", "category", "категория"],
    "account_hint": ["account", "card", "счет", "карта"],
    "source_reference": ["reference", "id", "номер", "rrn", "auth", "document"],
}

DATE_RX = re.compile(r"^\d{2}[./-]\d{2}[./-]\d{2,4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?$|^\d{4}-\d{2}-\d{2}$")
AMOUNT_RX = re.compile(r"^[-+]?\d[\d\s]*(?:[.,]\d{1,2})?$")
CURRENCY_RX = re.compile(r"^(RUB|USD|EUR|KZT|AED|GBP|₽|\$|€|₸)$", re.I)


class ImportRecognitionService:
    def __init__(self):
        self.confidence = ImportConfidenceService()

    def recognize(self, *, table: ExtractedTable) -> dict[str, Any]:
        schema = table.meta.get("schema")
        if schema == "normalized_transactions":
            return self._recognize_prestructured_table(table)
        if schema == "diagnostics":
            return self._recognize_diagnostics_table(table)

        columns = table.columns
        rows = table.rows
        column_analysis = [self._analyze_column(name=column, values=[row.get(column, "") for row in rows]) for column in columns]

        chosen_roles: dict[str, dict[str, Any]] = {}
        used_columns: set[str] = set()
        for role in HEADER_SYNONYMS.keys():
            candidates = sorted(column_analysis, key=lambda item: item["scores"].get(role, 0.0), reverse=True)
            best = next((item for item in candidates if item["name"] not in used_columns and item["scores"].get(role, 0.0) >= 0.45), None)
            if best:
                chosen_roles[role] = {
                    "column": best["name"],
                    "confidence": best["scores"][role],
                    "reason": best["reasons"].get(role, ""),
                }
                if role not in {"raw_type", "counterparty", "account_hint", "source_reference", "balance_after", "currency"}:
                    used_columns.add(best["name"])

        date_formats = self._guess_date_formats(rows, chosen_roles.get("date", {}).get("column"))
        unresolved = [role for role in ["date", "description"] if role not in chosen_roles]
        if "amount" not in chosen_roles and not ({"income", "expense"} <= set(chosen_roles.keys())):
            unresolved.append("amount")

        overall_confidence = 0.0
        if chosen_roles:
            overall_confidence = round(sum(item["confidence"] for item in chosen_roles.values()) / len(chosen_roles), 4)

        return {
            "selected_table": table.name,
            "available_tables": [{"name": table.name, "columns": table.columns, "rows": len(table.rows), "confidence": table.confidence}],
            "field_mapping": {role: item["column"] for role, item in chosen_roles.items()},
            "field_confidence": {role: item["confidence"] for role, item in chosen_roles.items()},
            "field_reasons": {role: item["reason"] for role, item in chosen_roles.items()},
            "column_analysis": column_analysis,
            "suggested_date_formats": date_formats,
            "overall_confidence": overall_confidence,
            "confidence_label": self.confidence.label(overall_confidence),
            "unresolved_fields": unresolved,
        }

    def _recognize_prestructured_table(self, table: ExtractedTable) -> dict[str, Any]:
        rows = table.rows
        required_roles = ["date", "description", "amount"]
        optional_roles = ["currency", "direction", "balance_after", "account_hint", "counterparty", "raw_type", "source_reference"]
        role_coverage = {role: self._coverage(rows, role) for role in required_roles + optional_roles}
        field_mapping = {role: role for role in table.columns if role in HEADER_SYNONYMS}
        field_confidence = {
            role: self.confidence.score_prestructured_role(role=role, coverage=role_coverage.get(role, 0.0), required=role in required_roles)
            for role in field_mapping.keys()
        }
        unresolved = [role for role in required_roles if role_coverage.get(role, 0.0) < 0.85]
        overall_confidence = self.confidence.score_prestructured_table(role_coverage=role_coverage, unresolved_fields=unresolved)

        column_analysis = [
            {
                "name": column,
                "coverage": round(role_coverage.get(column, self._coverage(rows, column)), 4),
                "sample_values": [row.get(column, "") for row in rows[:5] if row.get(column, "")],
                "scores": {column: field_confidence.get(column, 0.0)},
                "reasons": {column: f"prestructured_pdf coverage={role_coverage.get(column, 0.0):.2f}"},
            }
            for column in table.columns
        ]

        return {
            "selected_table": table.name,
            "available_tables": [{"name": table.name, "columns": table.columns, "rows": len(rows), "confidence": table.confidence}],
            "field_mapping": field_mapping,
            "field_confidence": field_confidence,
            "field_reasons": {role: f"prestructured_pdf coverage={role_coverage.get(role, 0.0):.2f}" for role in field_mapping.keys()},
            "column_analysis": column_analysis,
            "suggested_date_formats": self._guess_date_formats(rows, "date"),
            "overall_confidence": overall_confidence,
            "confidence_label": self.confidence.label(overall_confidence),
            "unresolved_fields": unresolved,
        }

    def _recognize_diagnostics_table(self, table: ExtractedTable) -> dict[str, Any]:
        return {
            "selected_table": table.name,
            "available_tables": [{"name": table.name, "columns": table.columns, "rows": len(table.rows), "confidence": table.confidence}],
            "field_mapping": {},
            "field_confidence": {},
            "field_reasons": {"diagnostics": "Структура PDF не распознана достаточно надёжно для автосопоставления."},
            "column_analysis": [
                {
                    "name": column,
                    "coverage": self._coverage(table.rows, column),
                    "sample_values": [row.get(column, "") for row in table.rows[:5] if row.get(column, "")],
                    "scores": {},
                    "reasons": {"diagnostics": "service_diagnostics"},
                }
                for column in table.columns
            ],
            "suggested_date_formats": ["%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"],
            "overall_confidence": 0.15,
            "confidence_label": "low",
            "unresolved_fields": ["date", "description", "amount"],
        }

    def _analyze_column(self, *, name: str, values: list[str]) -> dict[str, Any]:
        non_empty = [str(value).strip() for value in values if str(value).strip()]
        coverage = len(non_empty) / len(values) if values else 0.0
        lower_name = name.lower().strip()

        header_score: dict[str, float] = {}
        for role, variants in HEADER_SYNONYMS.items():
            header_score[role] = 1.0 if any(token in lower_name for token in variants) else 0.0

        value_signals = {
            "date": self._ratio(non_empty, lambda x: bool(DATE_RX.match(x))),
            "amount": self._ratio(non_empty, lambda x: bool(AMOUNT_RX.match(x.replace(" ", "")))),
            "income": self._ratio(non_empty, lambda x: bool(AMOUNT_RX.match(x.replace(" ", "")))) * (0.7 if "income" in lower_name or "credit" in lower_name or "приход" in lower_name else 0.3),
            "expense": self._ratio(non_empty, lambda x: bool(AMOUNT_RX.match(x.replace(" ", "")))) * (0.7 if "expense" in lower_name or "debit" in lower_name or "расход" in lower_name else 0.3),
            "currency": self._ratio(non_empty, lambda x: bool(CURRENCY_RX.match(x))),
            "direction": self._ratio(non_empty, lambda x: any(word in x.lower() for word in ["income", "expense", "credit", "debit", "приход", "расход", "спис", "пополн"])),
            "description": self._ratio(non_empty, lambda x: len(x) >= 5 and not DATE_RX.match(x) and not AMOUNT_RX.match(x.replace(" ", ""))),
            "balance_after": self._ratio(non_empty, lambda x: bool(AMOUNT_RX.match(x.replace(" ", "")))) * (0.8 if "остат" in lower_name or "balance" in lower_name else 0.4),
            "counterparty": self._ratio(non_empty, lambda x: len(x) >= 4 and any(ch.isalpha() for ch in x)) * (0.8 if any(tok in lower_name for tok in ["counterparty", "получ", "отправ", "контраг"]) else 0.3),
            "raw_type": self._ratio(non_empty, lambda x: len(x) >= 3 and any(ch.isalpha() for ch in x)) * (0.8 if "type" in lower_name or "тип" in lower_name or "катег" in lower_name else 0.3),
            "account_hint": self._ratio(non_empty, lambda x: len(x) >= 4) * (0.8 if any(tok in lower_name for tok in ["account", "card", "карта", "счет"]) else 0.2),
            "source_reference": self._ratio(non_empty, lambda x: len(x) >= 4) * (0.8 if any(tok in lower_name for tok in ["rrn", "ref", "номер", "id", "auth"]) else 0.2),
        }

        scores: dict[str, float] = {}
        reasons: dict[str, str] = {}
        for role in HEADER_SYNONYMS.keys():
            score = self.confidence.score_column_role(role=role, header_score=header_score.get(role, 0.0), value_score=value_signals.get(role, 0.0), coverage=coverage)
            scores[role] = score
            reasons[role] = f"header={header_score.get(role, 0.0):.2f}, values={value_signals.get(role, 0.0):.2f}, coverage={coverage:.2f}"

        return {
            "name": name,
            "coverage": round(coverage, 4),
            "sample_values": non_empty[:5],
            "scores": scores,
            "reasons": reasons,
        }

    @staticmethod
    def _ratio(values: list[str], predicate) -> float:
        if not values:
            return 0.0
        return round(sum(1 for value in values if predicate(value)) / len(values), 4)

    @staticmethod
    def _coverage(rows: list[dict[str, str]], column: str) -> float:
        if not rows:
            return 0.0
        return round(sum(1 for row in rows if str(row.get(column, "")).strip()) / len(rows), 4)

    @staticmethod
    def _guess_date_formats(rows: list[dict[str, str]], date_column: str | None) -> list[str]:
        if not date_column:
            return ["%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d"]
        samples = [row.get(date_column, "").strip() for row in rows[:20] if row.get(date_column, "").strip()]
        counter: Counter[str] = Counter()
        for sample in samples:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", sample):
                counter["%Y-%m-%d"] += 1
            if re.match(r"^\d{2}\.\d{2}\.\d{4}$", sample):
                counter["%d.%m.%Y"] += 1
            if re.match(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2}$", sample):
                counter["%d.%m.%Y %H:%M:%S"] += 1
            if re.match(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$", sample):
                counter["%d.%m.%Y %H:%M"] += 1
            if re.match(r"^\d{2}/\d{2}/\d{4}$", sample):
                counter["%d/%m/%Y"] += 1
            if re.match(r"^\d{2}-\d{2}-\d{4}$", sample):
                counter["%d-%m-%Y"] += 1
        ordered = [item[0] for item in counter.most_common()]
        fallback = ["%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]
        return ordered + [fmt for fmt in fallback if fmt not in ordered]
