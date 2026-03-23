from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExtractedTable:
    name: str
    columns: list[str]
    rows: list[dict[str, str]]
    confidence: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractionResult:
    source_type: str
    tables: list[ExtractedTable]
    meta: dict[str, Any] = field(default_factory=dict)


class BaseExtractor:
    source_type: str = "unknown"

    def extract(self, *, filename: str, raw_bytes: bytes, options: dict[str, Any] | None = None) -> ExtractionResult:
        raise NotImplementedError
