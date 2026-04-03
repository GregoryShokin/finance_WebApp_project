from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.import_extractors.base import BaseExtractor, ExtractedTable, ExtractionResult


DATE_ONLY_RX = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
TIME_ONLY_RX = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")
YANDEX_TIME_RX = re.compile(r"^в\s+(?P<time>\d{2}:\d{2})$")
TBANK_START_RX = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
OZON_START_RX = re.compile(r"^(?P<dt>\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}:\d{2})\s+(?P<doc>\S+)(?:\s+(?P<rest>.*))?$")
SIGNED_AMOUNT_RX = re.compile(r"([+\-–−])\s*([\d\s]+(?:[.,]\d{2}))\s*(?:₽|RUB|РУБ)?", re.I)
ANY_MONEY_RX = re.compile(r"([\d\s]+(?:[.,]\d{2}))\s*(?:₽|RUB|РУБ)", re.I)
CARD_TAIL_RX = re.compile(r"^\d{4}$")
DATE_AT_END_RX = re.compile(r"^(?P<text>.*\S)\s+(?P<date>\d{2}\.\d{2}\.\d{4})$")
YANDEX_SUMMARY_RX = re.compile(
    r"^(?P<posted>\d{2}\.\d{2}\.\d{4})(?:\s+(?P<card>\*\d{4}))?\s+"
    r"(?P<amount1>[+\-–−]?\d[\d\s]*,\d{2})\s*₽(?:\s+(?P<amount2>[+\-–−]?\d[\d\s]*,\d{2})\s*₽)?$"
)
# Кредитная выписка Яндекс Банка: дата + сумма + сумма (без знака)
YANDEX_CREDIT_ROW_RX = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<amount1>[\d\xa0\s]+,\d{2})\s*₽\s+"
    r"(?P<amount2>[\d\xa0\s]+,\d{2})\s*₽$"
)
# Однострочная запись: описание + дата + сумма + сумма
YANDEX_CREDIT_INLINE_RX = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<amount1>[\d\xa0\s]+,\d{2})\s*₽\s+"
    r"(?P<amount2>[\d\xa0\s]+,\d{2})\s*₽$"
)

SERVICE_LINE_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"^Исх\.",
        r"^АКЦИОНЕРНОЕ ОБЩЕСТВО",
        r"^АО .?ТБанк",
        r"^ООО .?ОЗОН Банк",
        r"^АО .?Яндекс Банк",
        r"^РОССИЯ,",
        r"^ТЕЛ\.:",
        r"^Справка о движении средств$",
        r"^Выписка по договору",
        r"^Выписка по Договору за период",
        r"^№ Ф-",
        r"^Владелец:",
        r"^Номер лицевого",
        r"^Дата и время формирования документа",
        r"^Период выписки:",
        r"^Валюта:",
        r"^Входящий остаток:",
        r"^Исходящий остаток:",
        r"^Итого зачислений за период:",
        r"^Итого списаний за период:",
        r"^С уважением,",
        r"^Руководитель управления",
        r"^мидл-офисных операций",
        r"^Лицензия Банка России",
        r"^ИНН/КПП",
        r"^Пресненская набережная",
        r"^вн\.тер\.г\.",
        r"^О продукте$",
        r"^Дата заключения договора:",
        r"^Номер договора:",
        r"^Номер лицевого счета:",
        r"^Движение средств за период",
        r"^Описание операции Дата и время$",
        r"^Дата и время$",
        r"^операции$",
        r"^МСК$",
        r"^Дата$",
        r"^обработки$",
        r"^списания$",
        r"^Сумма в валюте$",
        r"^Сумма операции$",
        r"^в валюте карты$",
        r"^Описание$",
        r"^Номер$",
        r"^карты$",
        r"^Дата операции Документ Назначение платежа$",
        r"^Российские рубли Валюта$",
        r"^ЭСП$",
        r"^Карта Сумма в валюте$",
        r"^Описание операции Дата операции Сумма в валюте$",
        r"^Дата операции$",
        r"^Сумма в валюте$",
        r"^Договора$",
        r"^Доступный лимит\s.*$",
        r"^Задолженность по лимиту\s.*$",
        r"^Входящий остаток на \d{2}\.\d{2}\.\d{4} .*$",
        r"^Исходящий остаток за \d{2}\.\d{2}\.\d{4} .*$",
        r"^Всего расходных операций$",
        r"^Всего приходных операций$",
        r"^Продолжение на следующей странице$",
        r"^Страница \d+ из \d+$",
        r"^\+\d[\d\s]*,\d{2} ₽$",
        r"^[\-–−]\d[\d\s]*,\d{2} ₽(?:Всего расходных операций)?$",
        r"^\d+\s*$",
    ]
]


@dataclass(slots=True)
class CandidateBlock:
    lines: list[str]
    layout: str


class PdfExtractor(BaseExtractor):
    source_type = "pdf"

    def extract(self, *, filename: str, raw_bytes: bytes, options: dict[str, Any] | None = None) -> ExtractionResult:
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
        except PdfReadError as exc:
            return ExtractionResult(
                source_type=self.source_type,
                tables=[self._diagnostics_table(reason="PDF повреждён, защищён паролем или имеет неподдерживаемую структуру.")],
                meta={
                    "page_count": 0,
                    "needs_ocr": False,
                    "text_based": False,
                    "diagnostics": {"reason": "pdf_read_error", "error": str(exc)},
                },
            )
        except Exception as exc:
            return ExtractionResult(
                source_type=self.source_type,
                tables=[self._diagnostics_table(reason="Не удалось открыть PDF для распознавания.")],
                meta={
                    "page_count": 0,
                    "needs_ocr": False,
                    "text_based": False,
                    "diagnostics": {"reason": "pdf_open_error", "error": str(exc)},
                },
            )

        if getattr(reader, "is_encrypted", False):
            try:
                decrypt_result = reader.decrypt("")
            except Exception as exc:
                decrypt_result = 0
                decrypt_error = str(exc)
            else:
                decrypt_error = None

            if not decrypt_result:
                return ExtractionResult(
                    source_type=self.source_type,
                    tables=[self._diagnostics_table(reason="PDF защищён паролем. Сними защиту и загрузи файл повторно.")],
                    meta={
                        "page_count": len(reader.pages),
                        "needs_ocr": False,
                        "text_based": False,
                        "diagnostics": {
                            "reason": "encrypted_pdf",
                            **({"error": decrypt_error} if decrypt_error else {}),
                        },
                    },
                )

        page_texts: list[str] = []
        page_stats: list[dict[str, Any]] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
                extract_error = None
            except Exception as exc:
                text = ""
                extract_error = str(exc)
            if text.strip():
                page_texts.append(text)
            page_stat = {"page": index, "text_length": len(text)}
            if extract_error:
                page_stat["extract_error"] = extract_error
            page_stats.append(page_stat)

        full_text = "\n".join(page_texts).strip()
        if not full_text:
            return ExtractionResult(
                source_type=self.source_type,
                tables=[self._diagnostics_table(reason="PDF не содержит извлекаемого текста. Нужен OCR fallback.")],
                meta={
                    "page_count": len(reader.pages),
                    "needs_ocr": True,
                    "text_based": False,
                    "diagnostics": {"reason": "no_text_extracted", "pages": page_stats},
                },
            )

        raw_lines = [self._normalize_line(line) for line in full_text.splitlines()]
        raw_lines = [line for line in raw_lines if line]

        if self._is_yandex_credit_statement(full_text):
            return self._extract_yandex_credit_statement(raw_lines=raw_lines, page_stats=page_stats, page_count=len(reader.pages))

        if self._is_yandex_bank_statement(full_text, raw_lines):
            return self._extract_yandex_bank_statement(raw_lines=raw_lines, page_stats=page_stats, page_count=len(reader.pages))

        filtered_lines = [line for line in raw_lines if not self._is_service_line(line)]
        candidate_blocks = self._segment_blocks(filtered_lines)
        parsed_rows: list[dict[str, str]] = []
        rejected_blocks: list[dict[str, str]] = []
        layout_counter: dict[str, int] = {}

        for block in candidate_blocks:
            layout_counter[block.layout] = layout_counter.get(block.layout, 0) + 1
            parsed = self._parse_block(block)
            if parsed:
                parsed_rows.append(parsed)
            else:
                rejected_blocks.append(
                    {
                        "raw_block": "\n".join(block.lines),
                        "diagnostic_reason": "Не удалось извлечь обязательные поля date/description/amount из блока.",
                        "layout_guess": block.layout,
                    }
                )

        tables: list[ExtractedTable] = []
        if parsed_rows:
            tables.append(
                ExtractedTable(
                    name="pdf_transactions",
                    columns=[
                        "date",
                        "description",
                        "amount",
                        "currency",
                        "direction",
                        "balance_after",
                        "account_hint",
                        "counterparty",
                        "raw_type",
                        "source_reference",
                    ],
                    rows=parsed_rows,
                    confidence=0.9 if len(parsed_rows) >= max(1, len(candidate_blocks) // 2) else 0.72,
                    meta={"schema": "normalized_transactions", "parser": "universal_pdf_pipeline_v2"},
                )
            )

        if rejected_blocks:
            tables.append(
                ExtractedTable(
                    name="pdf_diagnostics",
                    columns=["raw_block", "diagnostic_reason", "layout_guess"],
                    rows=rejected_blocks[:50],
                    confidence=0.25,
                    meta={"schema": "diagnostics", "parser": "universal_pdf_pipeline_v2"},
                )
            )

        if not tables:
            tables.append(self._diagnostics_table(reason="Не удалось выделить ни одного блока транзакций."))

        return ExtractionResult(
            source_type=self.source_type,
            tables=tables,
            meta={
                "page_count": len(reader.pages),
                "needs_ocr": False,
                "text_based": True,
                "line_count": len(raw_lines),
                "filtered_line_count": len(filtered_lines),
                "candidate_block_count": len(candidate_blocks),
                "parsed_transaction_count": len(parsed_rows),
                "rejected_block_count": len(rejected_blocks),
                "layout_counts": layout_counter,
                "preview_text": "\n".join(raw_lines[:40]),
                "diagnostics": {
                    "pages": page_stats,
                    "sample_filtered_lines": filtered_lines[:20],
                    "sample_candidate_blocks": ["\n".join(block.lines[:8]) for block in candidate_blocks[:5]],
                    "sample_rejected_blocks": rejected_blocks[:5],
                },
            },
        )

    @staticmethod
    def _is_yandex_credit_statement(full_text: str) -> bool:
        return (
            "АО «Яндекс Банк»" in full_text
            and "Выписка по Договору за период" in full_text
            and (
                "Потребительский кредит" in full_text
                or "Задолженность по лимиту" in full_text
                or "Доступный лимит" in full_text
            )
        )

    def _extract_yandex_credit_statement(
        self,
        *,
        raw_lines: list[str],
        page_stats: list[dict[str, Any]],
        page_count: int,
    ) -> ExtractionResult:
        statement_lines = self._slice_yandex_credit_lines(raw_lines)
        filtered_lines = [line for line in statement_lines if not self._is_service_line(line)]
        parsed_rows, rejected_blocks = self._parse_yandex_credit_rows(filtered_lines)
        tables: list[ExtractedTable] = []

        if parsed_rows:
            tables.append(
                ExtractedTable(
                    name="pdf_transactions",
                    columns=[
                        "date", "posted_date", "description", "amount",
                        "currency", "direction", "balance_after",
                        "account_hint", "counterparty", "raw_type", "source_reference",
                    ],
                    rows=parsed_rows,
                    confidence=0.94 if len(parsed_rows) >= 3 else 0.80,
                    meta={"schema": "normalized_transactions", "parser": "yandex_credit_pdf_v1"},
                )
            )

        if rejected_blocks:
            tables.append(
                ExtractedTable(
                    name="pdf_diagnostics",
                    columns=["raw_block", "diagnostic_reason", "layout_guess"],
                    rows=rejected_blocks[:50],
                    confidence=0.25,
                    meta={"schema": "diagnostics", "parser": "yandex_credit_pdf_v1"},
                )
            )

        if not tables:
            tables.append(self._diagnostics_table(reason="Не удалось распознать операции кредитной выписки Яндекс Банка."))

        return ExtractionResult(
            source_type=self.source_type,
            tables=tables,
            meta={
                "page_count": page_count,
                "needs_ocr": False,
                "text_based": True,
                "line_count": len(raw_lines),
                "filtered_line_count": len(filtered_lines),
                "parsed_transaction_count": len(parsed_rows),
                "rejected_block_count": len(rejected_blocks),
                "layout_counts": {"yandex_credit_block": len(parsed_rows) + len(rejected_blocks)},
                "preview_text": "\n".join(raw_lines[:40]),
                "diagnostics": {
                    "pages": page_stats,
                    "sample_filtered_lines": filtered_lines[:25],
                    "sample_rejected_blocks": rejected_blocks[:5],
                },
            },
        )

    @staticmethod
    def _slice_yandex_credit_lines(raw_lines: list[str]) -> list[str]:
        # Начинаем после заголовка "Договора" (последний столбец)
        start_index = 0
        for idx, line in enumerate(raw_lines):
            if line.strip() == "Договора":
                start_index = idx + 1
                break
        # Заканчиваем перед строкой с отдельной суммой или "Всего"
        end_index = len(raw_lines)
        standalone_amount = re.compile(r"^[\d\xa0\s]+,\d{2}\s*₽$")
        for idx in range(start_index, len(raw_lines)):
            line = raw_lines[idx]
            if standalone_amount.match(line):
                end_index = idx
                break
            if line.startswith("Всего расходных") or line.startswith("Всего приходных"):
                end_index = idx
                break
        return raw_lines[start_index:end_index]

    def _parse_yandex_credit_rows(
        self, lines: list[str]
    ) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        rows: list[dict[str, str]] = []
        rejected: list[dict[str, str]] = []
        index = 0

        while index < len(lines):
            # Однострочный вариант: описание + дата + суммы на одной строке
            inline = YANDEX_CREDIT_INLINE_RX.match(lines[index])
            if inline:
                row = self._build_yandex_credit_row(
                    description=inline.group("desc").strip(),
                    date=inline.group("date"),
                    amount_raw=inline.group("amount1"),
                )
                if row:
                    rows.append(row)
                index += 1
                continue

            # Многострочный вариант: сначала описание, потом дата+суммы
            desc_parts: list[str] = []
            start_index = index
            found = False
            while index < len(lines):
                line = lines[index]
                m = YANDEX_CREDIT_ROW_RX.match(line)
                if m:
                    description = " ".join(desc_parts).strip()
                    if description:
                        row = self._build_yandex_credit_row(
                            description=description,
                            date=m.group("date"),
                            amount_raw=m.group("amount1"),
                        )
                        if row:
                            rows.append(row)
                    else:
                        rejected.append({
                            "raw_block": line,
                            "diagnostic_reason": "нет описания у строки даты/суммы",
                            "layout_guess": "yandex_credit_block",
                        })
                    index += 1
                    found = True
                    break
                desc_parts.append(line)
                index += 1

            if not found and desc_parts:
                rejected.append({
                    "raw_block": "\n".join(desc_parts),
                    "diagnostic_reason": "нет строки даты/суммы после описания",
                    "layout_guess": "yandex_credit_block",
                })

        return rows, rejected

    def _build_yandex_credit_row(
        self,
        *,
        description: str,
        date: str,
        amount_raw: str,
    ) -> dict[str, str] | None:
        if not description:
            return None
        amount_norm = self._normalize_amount(amount_raw)
        lower = description.lower()
        if "отмена" in lower or "возврат" in lower:
            direction = "income"
            sign = "+"
        else:
            direction = "expense"
            sign = "-"
        amount = f"{sign}{amount_norm}"
        raw_type = self._classify_yandex_raw_type(description)
        counterparty = self._extract_counterparty(description)
        return {
            "date": date,
            "posted_date": date,
            "description": description,
            "amount": amount,
            "currency": "RUB",
            "direction": direction,
            "balance_after": "",
            "account_hint": "",
            "counterparty": counterparty,
            "raw_type": raw_type,
            "source_reference": date,
        }

    @staticmethod
    def _is_yandex_bank_statement(full_text: str, raw_lines: list[str]) -> bool:
        markers = [
            "АО «Яндекс Банк»",
            "Счёт ЭДС",
            "Выписка по Договору за период",
        ]
        marker_hits = sum(1 for marker in markers if marker in full_text)
        if marker_hits >= 2:
            return True
        return any("Яндекс Банк" in line for line in raw_lines) and any("Счёт ЭДС" in line for line in raw_lines)

    def _extract_yandex_bank_statement(
        self,
        *,
        raw_lines: list[str],
        page_stats: list[dict[str, Any]],
        page_count: int,
    ) -> ExtractionResult:
        statement_lines = self._slice_yandex_transaction_lines(raw_lines)
        filtered_lines = [line for line in statement_lines if not self._is_service_line(line)]
        parsed_rows, rejected_blocks = self._parse_yandex_rows(filtered_lines)
        tables: list[ExtractedTable] = []

        if parsed_rows:
            tables.append(
                ExtractedTable(
                    name="pdf_transactions",
                    columns=[
                        "date",
                        "posted_date",
                        "description",
                        "amount",
                        "currency",
                        "direction",
                        "balance_after",
                        "account_hint",
                        "counterparty",
                        "raw_type",
                        "source_reference",
                    ],
                    rows=parsed_rows,
                    confidence=0.96 if len(parsed_rows) >= 3 else 0.82,
                    meta={"schema": "normalized_transactions", "parser": "yandex_bank_pdf_v1"},
                )
            )

        if rejected_blocks:
            tables.append(
                ExtractedTable(
                    name="pdf_diagnostics",
                    columns=["raw_block", "diagnostic_reason", "layout_guess"],
                    rows=rejected_blocks[:50],
                    confidence=0.25,
                    meta={"schema": "diagnostics", "parser": "yandex_bank_pdf_v1"},
                )
            )

        if not tables:
            tables.append(self._diagnostics_table(reason="Не удалось распознать операции Яндекс Банка."))

        return ExtractionResult(
            source_type=self.source_type,
            tables=tables,
            meta={
                "page_count": page_count,
                "needs_ocr": False,
                "text_based": True,
                "line_count": len(raw_lines),
                "filtered_line_count": len(filtered_lines),
                "candidate_block_count": len(parsed_rows) + len(rejected_blocks),
                "parsed_transaction_count": len(parsed_rows),
                "rejected_block_count": len(rejected_blocks),
                "layout_counts": {"yandex_statement_block": len(parsed_rows) + len(rejected_blocks)},
                "preview_text": "\n".join(raw_lines[:40]),
                "diagnostics": {
                    "pages": page_stats,
                    "sample_filtered_lines": filtered_lines[:25],
                    "sample_rejected_blocks": rejected_blocks[:5],
                },
            },
        )


    @staticmethod
    def _slice_yandex_transaction_lines(raw_lines: list[str]) -> list[str]:
        start_index = 0
        for idx, line in enumerate(raw_lines):
            if line == "ЭСП":
                start_index = idx + 1
                break
        end_index = len(raw_lines)
        for idx in range(start_index, len(raw_lines)):
            line = raw_lines[idx]
            if line.startswith("Исходящий остаток за "):
                end_index = idx
                break
        return raw_lines[start_index:end_index]

    def _parse_yandex_rows(self, lines: list[str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        rows: list[dict[str, str]] = []
        rejected: list[dict[str, str]] = []
        index = 0

        while index < len(lines):
            start_index = index
            description_parts: list[str] = []
            operation_date: str | None = None

            while index < len(lines):
                line = lines[index]
                if self._looks_like_yandex_summary_line(line):
                    operation_date = line
                    index += 1
                    break

                embedded = DATE_AT_END_RX.match(line)
                if embedded and not self._looks_like_pure_service_description(line):
                    description_parts.append(embedded.group("text"))
                    operation_date = embedded.group("date")
                    index += 1
                    break

                description_parts.append(line)
                index += 1

            if not description_parts and operation_date is None:
                index += 1
                continue

            time_line = lines[index] if index < len(lines) else ""
            time_match = YANDEX_TIME_RX.match(time_line)
            summary_line = lines[index + 1] if time_match and index + 1 < len(lines) else ""

            if operation_date is None or not time_match or not summary_line:
                rejected.append(
                    {
                        "raw_block": "\n".join(lines[start_index:min(len(lines), max(index + 2, start_index + 1))]),
                        "diagnostic_reason": "Не удалось определить дату/время/сумму операции Яндекс Банка.",
                        "layout_guess": "yandex_statement_block",
                    }
                )
                index = max(index, start_index + 1)
                continue

            parsed = self._parse_yandex_block(
                description_parts=description_parts,
                operation_date=operation_date,
                operation_time=time_match.group("time"),
                summary_line=summary_line,
            )
            if parsed is None:
                rejected.append(
                    {
                        "raw_block": "\n".join(lines[start_index:min(len(lines), index + 2)]),
                        "diagnostic_reason": "Не удалось извлечь обязательные поля из блока Яндекс Банка.",
                        "layout_guess": "yandex_statement_block",
                    }
                )
                index += 2
                continue

            rows.append(parsed)
            index += 2

        return rows, rejected

    def _parse_yandex_block(
        self,
        *,
        description_parts: list[str],
        operation_date: str,
        operation_time: str,
        summary_line: str,
    ) -> dict[str, str] | None:
        summary_match = YANDEX_SUMMARY_RX.match(summary_line)
        if not summary_match:
            return None

        description = self._join_description(description_parts)
        if not description:
            return None

        amount_raw = summary_match.group("amount1")
        amount = self._normalize_signed_amount(amount_raw)
        direction = "income" if amount.startswith("+") else "expense"
        posted_date = summary_match.group("posted")
        account_hint = (summary_match.group("card") or "").strip()
        balance_after = ""
        second_amount = summary_match.group("amount2")
        if second_amount:
            normalized_second = self._normalize_signed_amount(second_amount)
            if normalized_second != amount:
                balance_after = normalized_second.lstrip("+-")

        operation_datetime = f"{operation_date} {operation_time}"
        counterparty = self._extract_counterparty(description)
        raw_type = self._classify_yandex_raw_type(description)
        source_reference = f"{posted_date}|{account_hint}".strip("|")

        return {
            "date": operation_datetime,
            "posted_date": posted_date,
            "description": description,
            "amount": amount,
            "currency": "RUB",
            "direction": direction,
            "balance_after": balance_after,
            "account_hint": account_hint,
            "counterparty": counterparty,
            "raw_type": raw_type,
            "source_reference": source_reference,
        }

    @staticmethod
    def _looks_like_pure_service_description(line: str) -> bool:
        lowered = line.lower()
        return lowered.startswith("входящий остаток") or lowered.startswith("исходящий остаток")

    @staticmethod
    def _looks_like_yandex_summary_line(line: str) -> bool:
        return bool(DATE_ONLY_RX.match(line))

    def _segment_blocks(self, lines: list[str]) -> list[CandidateBlock]:
        blocks: list[CandidateBlock] = []
        current: list[str] = []
        current_layout: str | None = None

        for idx, line in enumerate(lines):
            layout = self._detect_block_start(lines, idx)
            if layout:
                if current:
                    blocks.append(CandidateBlock(lines=current, layout=current_layout or "unknown"))
                current = [line]
                current_layout = layout
                continue

            if current:
                current.append(line)

        if current:
            blocks.append(CandidateBlock(lines=current, layout=current_layout or "unknown"))

        return blocks

    def _detect_block_start(self, lines: list[str], idx: int) -> str | None:
        line = lines[idx]
        if OZON_START_RX.match(line):
            return "datetime_doc_amount_block"

        if not TBANK_START_RX.match(line):
            return None
        if idx + 4 >= len(lines):
            return None
        if TIME_ONLY_RX.match(lines[idx + 1]) and DATE_ONLY_RX.match(lines[idx + 2]) and TIME_ONLY_RX.match(lines[idx + 3]):
            if SIGNED_AMOUNT_RX.search(lines[idx + 4]) or ANY_MONEY_RX.search(lines[idx + 4]):
                return "paired_date_time_block"
        return None

    def _parse_block(self, block: CandidateBlock) -> dict[str, str] | None:
        if block.layout == "datetime_doc_amount_block":
            return self._parse_datetime_doc_block(block.lines)
        if block.layout == "paired_date_time_block":
            return self._parse_paired_date_time_block(block.lines)
        return None

    def _parse_datetime_doc_block(self, lines: list[str]) -> dict[str, str] | None:
        first = lines[0]
        start = OZON_START_RX.match(first)
        if not start:
            return None
        date_value = start.group("dt")
        source_reference = start.group("doc")
        description_parts = [part for part in [start.group("rest") or ""] if part]
        balance_after = None
        signed_matches: list[tuple[str, str]] = []

        for line in lines[1:]:
            signed_matches.extend(SIGNED_AMOUNT_RX.findall(line))
            if not SIGNED_AMOUNT_RX.search(line):
                description_parts.append(line)

        signed_matches = signed_matches or SIGNED_AMOUNT_RX.findall(first)
        if not signed_matches:
            return None

        sign, amount_value = signed_matches[0]
        amount = f"{self._normalize_sign(sign)}{self._normalize_amount(amount_value)}"
        if len(signed_matches) > 1:
            _, balance_value = signed_matches[-1]
            normalized_balance = self._normalize_amount(balance_value)
            if normalized_balance != self._normalize_amount(amount_value):
                balance_after = normalized_balance

        description = self._join_description(description_parts)
        if not description:
            return None

        return {
            "date": date_value,
            "description": description,
            "amount": amount,
            "currency": "RUB",
            "direction": "income" if sign == "+" else "expense",
            "balance_after": balance_after or "",
            "account_hint": "",
            "counterparty": self._extract_counterparty(description),
            "raw_type": self._classify_raw_type(description),
            "source_reference": source_reference,
        }

    def _parse_paired_date_time_block(self, lines: list[str]) -> dict[str, str] | None:
        if len(lines) < 5:
            return None
        date_value = f"{lines[0]} {lines[1]}"
        header_line = lines[4]
        signed_matches = SIGNED_AMOUNT_RX.findall(header_line)
        if not signed_matches:
            signed_matches = [m for m in SIGNED_AMOUNT_RX.findall(" ".join(lines))]
        if not signed_matches:
            return None

        sign, amount_value = signed_matches[0]
        amount = f"{self._normalize_sign(sign)}{self._normalize_amount(amount_value)}"
        balance_after = ""
        if len(signed_matches) > 1:
            _, balance_value = signed_matches[-1]
            normalized_balance = self._normalize_amount(balance_value)
            if normalized_balance != self._normalize_amount(amount_value):
                balance_after = normalized_balance

        description_parts: list[str] = []
        cleaned_header = SIGNED_AMOUNT_RX.sub("", header_line).strip(" -–—\t")
        if cleaned_header:
            description_parts.append(cleaned_header)

        account_hint = ""
        for line in lines[5:]:
            if CARD_TAIL_RX.match(line):
                account_hint = line
                continue
            description_parts.append(line)

        description = self._join_description(description_parts)
        if not description:
            return None

        return {
            "date": date_value,
            "description": description,
            "amount": amount,
            "currency": "RUB",
            "direction": "income" if sign == "+" else "expense",
            "balance_after": balance_after,
            "account_hint": account_hint,
            "counterparty": self._extract_counterparty(description),
            "raw_type": self._classify_raw_type(description),
            "source_reference": "",
        }

    @staticmethod
    def _normalize_line(value: str) -> str:
        value = value.replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _is_service_line(self, line: str) -> bool:
        if not line:
            return True
        return any(pattern.search(line) for pattern in SERVICE_LINE_PATTERNS)

    @staticmethod
    def _normalize_amount(value: str) -> str:
        return value.replace("\xa0", "").replace(" ", "").replace(",", ".")

    @classmethod
    def _normalize_signed_amount(cls, value: str) -> str:
        normalized = value.replace("₽", "").strip()
        sign = ""
        if normalized and normalized[0] in "+-–−":
            sign = cls._normalize_sign(normalized[0])
            normalized = normalized[1:].strip()
        normalized_amount = cls._normalize_amount(normalized)
        return f"{sign}{normalized_amount}" if sign else normalized_amount

    @staticmethod
    def _normalize_sign(value: str) -> str:
        return "+" if value == "+" else "-"

    @staticmethod
    def _join_description(parts: list[str]) -> str:
        cleaned = [part.strip(" -–—\t") for part in parts if part and part.strip(" -–—\t")]
        return re.sub(r"\s+", " ", " ".join(cleaned)).strip()

    @staticmethod
    def _extract_counterparty(description: str) -> str:
        lower = description.lower()
        if "отправитель:" in lower:
            return description.split("Отправитель:", 1)[-1].strip()
        if description.lower().startswith("входящий перевод сбп,"):
            parts = [part.strip() for part in description.split(",")]
            if len(parts) >= 2:
                return ", ".join(parts[1:]).strip()
        if description.lower().startswith("входящий перевод с карты"):
            return description
        return ""

    @staticmethod
    def _classify_raw_type(description: str) -> str:
        lower = description.lower()
        if "сбп" in lower or "перевод" in lower:
            return "transfer"
        if "погашение кредита" in lower or "кредит" in lower:
            return "loan_payment"
        if "оплата" in lower:
            return "card_payment"
        return "operation"

    @staticmethod
    def _classify_yandex_raw_type(description: str) -> str:
        lower = description.lower()
        if "погашение процентов" in lower:
            return "card_payment"
        if "погашение основного долга" in lower or "погашение просроченной" in lower:
            return "credit_payment"
        if lower.startswith("входящий перевод"):
            return "transfer"
        if "оплата" in lower:
            return "card_payment"
        return "operation"

    @staticmethod
    def _diagnostics_table(*, reason: str) -> ExtractedTable:
        return ExtractedTable(
            name="pdf_diagnostics",
            columns=["raw_block", "diagnostic_reason", "layout_guess"],
            rows=[{"raw_block": "", "diagnostic_reason": reason, "layout_guess": "unknown"}],
            confidence=0.1,
            meta={"schema": "diagnostics", "parser": "universal_pdf_pipeline_v2"},
        )
