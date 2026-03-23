from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class ImportConfidenceService:
    def score_column_role(self, *, role: str, header_score: float, value_score: float, coverage: float) -> float:
        role_bonus = 0.05 if role in {"date", "amount", "description", "direction"} else 0.0
        score = header_score * 0.45 + value_score * 0.45 + coverage * 0.1 + role_bonus
        return round(max(0.0, min(1.0, score)), 4)

    def score_row(
        self,
        *,
        issues: list[str],
        unresolved_fields: list[str],
        duplicate: bool = False,
        detected_fields: Mapping[str, Any] | None = None,
        row_status: str | None = None,
        assignment_reasons: list[str] | None = None,
    ) -> float:
        """Row confidence scoring.

        `issues` should only contain actual problems that require user attention.
        Informational auto-assignment explanations are accepted separately via
        `assignment_reasons` and do not reduce confidence.
        """

        score = 0.98

        mapping = dict(detected_fields or {})
        required_fields = ("date", "description", "amount")
        optional_fields = ("currency", "direction")
        mapped_required = sum(1 for field in required_fields if str(mapping.get(field) or "").strip())
        mapped_optional = sum(1 for field in optional_fields if str(mapping.get(field) or "").strip())

        if mapping:
            score -= max(0, len(required_fields) - mapped_required) * 0.05
            score += mapped_optional * 0.01

        score -= min(len(issues) * 0.18, 0.54)
        score -= min(len(unresolved_fields) * 0.08, 0.24)

        effective_duplicate = duplicate or row_status == "duplicate"
        if effective_duplicate:
            score -= 0.12

        if row_status == "warning":
            score -= 0.04
        elif row_status == "error":
            score -= 0.2
        elif row_status == "ready":
            score += 0.01

        informative_reasons = [reason for reason in (assignment_reasons or []) if str(reason or "").strip()]
        if informative_reasons:
            score += min(0.03 + len(informative_reasons) * 0.01, 0.06)

        if not issues and not unresolved_fields and row_status == "ready":
            score += 0.02

        return round(max(0.0, min(1.0, score)), 4)

    def score_prestructured_role(self, *, role: str, coverage: float, required: bool) -> float:
        baseline = 0.94 if required else 0.84
        score = baseline * coverage + (0.04 if required and coverage >= 0.95 else 0.0)
        return round(max(0.0, min(1.0, score)), 4)

    def score_prestructured_table(self, *, role_coverage: dict[str, float], unresolved_fields: list[str]) -> float:
        required = [role_coverage.get("date", 0.0), role_coverage.get("description", 0.0), role_coverage.get("amount", 0.0)]
        optional = [role_coverage.get("currency", 0.0), role_coverage.get("direction", 0.0)]
        if not required:
            return 0.0
        score = sum(required) / len(required) * 0.85 + (sum(optional) / len(optional) if optional else 0.0) * 0.15
        score -= min(len(unresolved_fields) * 0.15, 0.45)
        return round(max(0.0, min(1.0, score)), 4)

    def label(self, score: float) -> str:
        if score >= 0.85:
            return "high"
        if score >= 0.65:
            return "medium"
        return "low"
