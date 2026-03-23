from app.services.import_extractors.base import BaseExtractor, ExtractedTable, ExtractionResult
from app.services.import_extractors.csv_extractor import CsvExtractor
from app.services.import_extractors.pdf_extractor import PdfExtractor
from app.services.import_extractors.xlsx_extractor import XlsxExtractor


class ImportExtractorRegistry:
    def __init__(self) -> None:
        self._extractors = {
            "csv": CsvExtractor(),
            "xlsx": XlsxExtractor(),
            "pdf": PdfExtractor(),
        }

    def get(self, source_type: str) -> BaseExtractor | None:
        return self._extractors.get((source_type or "").strip().lower())

    def supported_types(self) -> list[str]:
        return list(self._extractors.keys())


__all__ = [
    "BaseExtractor",
    "ExtractedTable",
    "ExtractionResult",
    "CsvExtractor",
    "XlsxExtractor",
    "PdfExtractor",
    "ImportExtractorRegistry",
]
