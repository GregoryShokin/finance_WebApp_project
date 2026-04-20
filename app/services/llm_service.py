from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.category import Category

logger = logging.getLogger(__name__)


class TransactionClassification(BaseModel):
    category_id: int | None = Field(
        description="ID of the best-matching category, or null if no category fits."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence from 0 to 1."
    )
    reasoning: str = Field(
        description="Short explanation in Russian, max 120 chars."
    )


SYSTEM_PROMPT_TEMPLATE = """Ты — классификатор банковских транзакций для личного финансового приложения на русском языке.

Твоя задача: по описанию транзакции выбрать наиболее подходящую категорию из предоставленного списка.

Правила:
1. Анализируй описание целиком: названия магазинов, мерчантов, ключевые слова.
2. Учитывай тип транзакции (расход/доход) — выбирай только категорию правильного вида.
3. Если ни одна категория не подходит с уверенностью выше 0.5 — верни category_id = null.
4. confidence 0.9+ — точное совпадение (магазин известен, однозначная категория).
5. confidence 0.7-0.9 — вероятное совпадение (есть уверенные признаки).
6. confidence 0.5-0.7 — предположение (слабые признаки).
7. confidence < 0.5 — не угадывай, верни null.
8. reasoning — короткое объяснение на русском (до 120 символов), почему выбрал эту категорию.

Доступные категории пользователя:
{categories_block}

Валюта всех транзакций: рубли (RUB)."""


class LLMService:
    def __init__(self) -> None:
        self._client = None
        self._model = settings.ANTHROPIC_MODEL
        self._min_confidence = settings.LLM_MIN_CONFIDENCE
        self._enabled = bool(
            settings.LLM_CLASSIFICATION_ENABLED and settings.ANTHROPIC_API_KEY
        )

        if self._enabled:
            try:
                import anthropic

                self._client = anthropic.Anthropic(
                    api_key=settings.ANTHROPIC_API_KEY
                )
            except Exception as exc:
                logger.warning("Failed to init Anthropic client: %s", exc)
                self._enabled = False

    @property
    def is_enabled(self) -> bool:
        return self._enabled and self._client is not None

    def classify_transaction_category(
        self,
        *,
        description: str,
        amount: Decimal | float | None,
        transaction_type: str,
        categories: list["Category"],
        counterparty: str | None = None,
    ) -> tuple[int | None, float, str]:
        if not self.is_enabled:
            return None, 0.0, ""

        filtered = [c for c in categories if c.kind == transaction_type]
        if not filtered:
            return None, 0.0, ""

        categories_block = "\n".join(
            f"- ID {c.id}: {c.name} ({c.kind})" for c in filtered
        )
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            categories_block=categories_block
        )

        user_message_parts = [
            f"Описание: {description or '(пусто)'}",
            f"Сумма: {amount} RUB" if amount is not None else "Сумма: неизвестна",
            f"Тип: {'расход' if transaction_type == 'expense' else 'доход'}",
        ]
        if counterparty:
            user_message_parts.append(f"Контрагент: {counterparty}")
        user_message = "\n".join(user_message_parts)

        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
                output_format=TransactionClassification,
            )
        except Exception as exc:
            logger.warning("LLM classification failed: %s", exc)
            return None, 0.0, ""

        parsed: TransactionClassification | None = getattr(
            response, "parsed_output", None
        )
        if parsed is None:
            return None, 0.0, ""

        if parsed.category_id is None or parsed.confidence < self._min_confidence:
            return None, 0.0, ""

        valid_ids = {c.id for c in filtered}
        if parsed.category_id not in valid_ids:
            logger.info(
                "LLM returned invalid category_id=%s", parsed.category_id
            )
            return None, 0.0, ""

        reasoning = f"LLM: {parsed.reasoning}".strip()[:250]
        return parsed.category_id, float(parsed.confidence), reasoning
